import os
import json
import time
import pickle
import logging
import asyncio
import threading
from datetime import datetime
import joblib

import numpy as np
import pandas as pd
from streamz import Stream
from dotenv import load_dotenv

from models_server.data_scheme import cNetworkData, cSensorData
from models_server.data_config import NETWORK_FEATURE_LIST, SENSOR_FEATURE_LIST
from logging_setup import get_logger
# Load environment variables from .env file in the main script directory
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, "..", ".env")
load_dotenv(env_path)

TCP_HOST_IP             = os.getenv("TCP_HOST_IP")
NETWORK_DATA_TCP_PORT   = os.getenv("NETWORK_DATA_TCP_PORT")
SENSOR_DATA_TCP_PORT    = os.getenv("SENSOR_DATA_TCP_PORT")
EDGE_DEVICE_ID          = os.getenv("EDGE_DEVICE_ID")
NETWORK_ENCODER         = os.getenv("NETWORK_ENCODER")
NETWORK_SCALER          = os.getenv("NETWORK_SCALER")
SENSOR_SCALER           = os.getenv("SENSOR_SCALER")

class NetworkProbe:
    def __init__(self, network_stream=None):
        self.network_stream = network_stream or Stream(asynchronous=True)
        self._server = None
        self._server_task = None
        self.logger = get_logger("NetworkProbe")
        # self.logger = CustomLogger(LOGS_PATH)
        self.encoders = None
        self.scaler = None
        self.features_to_keep = NETWORK_FEATURE_LIST
        self.flow_counter = 0
        self._lock = threading.Lock()
        self.detect_stream = self.network_stream.map(self._preprocess_and_parse_flow)
        self.logger.info("NetworkProbe initialized.")

    def _preprocess_and_parse_flow(self, b: bytes):
        
        if self.encoders is None or self.scaler is None:
            self.logger.error("Encoder or scaler not set.")
            return None

        if self.scaler.n_features_in_ != len(self.features_to_keep):
            self.logger.error(
                f"Scaler expects {self.scaler.n_features_in_} features, "
                f"but {len(self.features_to_keep)} provided."
            )
            return None
        
        if set(self.scaler.feature_names_in_) != set(self.features_to_keep):
            self.logger.error("Feature set mismatch!")
            return None

        # 1. Decode bytes
        s = b.rstrip(b"\n").decode("utf-8", "replace")
        if not s:
            return None

        try:
            js = json.loads(s)
        except Exception as e:
            self.logger.exception(f"[JSON ERROR] {e} :: {s[:200]}")
            return None

        # Safe extraction
        SRC_IP = js.get("src_ip", "")
        DST_IP = js.get("dst_ip", "")
        SRC_PORT = js.get("src_port", 0)
        DST_PORT = js.get("dst_port", 0)
        PROTOCOL = js.get("protocol", "")

        # Extract features
        #low_list = [js.get(feat) for feat in self.features_to_keep]
        #print(js)

        # Lock the whole critical block
        with self._lock:
            try:
                encoded_scaled = self.encode_scale_flow(js).flatten().tolist()

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                log = {"flow_count": self.flow_counter}

                pkg = cNetworkData(
                    EDGE_DEVICE_ID,
                    timestamp,
                    SRC_IP,
                    DST_IP,
                    SRC_PORT,
                    DST_PORT,
                    PROTOCOL,   
                    encoded_scaled,
                    log
                )
                #print( pkg.to_json())
                self.flow_counter += 1
                return pkg.to_json()

            except Exception as e:
                self.logger.exception(f"[FLOW ERROR] {e} :: {[js.get(feat) for feat in self.features_to_keep]}")
                return None
    
    def encode_scale_flow(self, js_dict: dict):
        encoded = {}

        # No lock here, outer code handles locking
        for feat in self.features_to_keep:
            value = js_dict.get(feat)

            # If feature has an encoder:
            if feat in self.encoders:
                enc = self.encoders[feat]
            #    This should now be safe
                value = enc.transform([[value]])[0][0]

            encoded[feat] = value

        df_encoded = pd.DataFrame([encoded])

        scaled_encoded = self.scaler.transform(df_encoded)
        # print("------------------------------")
        # print(f"[DEBUG] Encoded input: {encoded}")
        # print(f"[DEBUG] Scaled input: {scaled_encoded}")
        # print("------------------------------")
        return scaled_encoded 

    async def create_tcp_server(self, host=TCP_HOST_IP, port=NETWORK_DATA_TCP_PORT):
        """
        Asynchronously creates and starts a TCP server that listens for incoming connections.
        The server listens on the specified host and port (default: '0.0.0.0' and 9000).
        For each client connection, it reads incoming data line by line and emits each line
        to the `network_stream` asynchronously, supporting backpressure.
        Parameters:
            host (str): The hostname or IP address to bind the server to. Defaults to '0.0.0.0'.
            port (int): The port number to listen on. Defaults to 9000.
        Notes:
            - The server runs indefinitely until cancelled.
            - Properly closes client connections after communication ends.
            - Assumes `self.network_stream.emit` is an awaitable method for handling incoming data.
        """
        async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                while True:
                    line = await reader.readline()  # reads until b"\n" or EOF
                    if not line:
                        break
                    # IMPORTANT: in async mode, emit returns an awaitable — await it
                    await self.network_stream.emit(line)    # backpressure-friendly
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
        
        server = await asyncio.start_server(_handle_client, host, port)
        # print(f"TCP server listening on {host}:{port}")
        self.logger.info(f"TCP server listening on {host}:{port}")
        
        async with server:
            await server.serve_forever()

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                self.logger.info("Server task cancelled.")
                pass
    
    def load_network_encoder(self):    
        try:
            with open(NETWORK_ENCODER, "rb") as f:
                self.encoders = pickle.load(f)
                return None
        except Exception as e:
            error_msg = f"Failed to load encoders from {NETWORK_ENCODER}: {e}"
            self.logger.error(error_msg, exc_info=True)  

    def load_network_scaler(self): 
        """
        Adding a min-max scaler for scaling the features.
        """
        try:
            with open(NETWORK_SCALER, "rb") as f:
                self.scaler = pickle.load(f)
        except Exception as e:
            error_msg = f"Failed to load encoders from {NETWORK_SCALER}: {e}"
            print(error_msg)
            self.logger.error(error_msg, exc_info=True)
            return None






class SensorProbe:
    def __init__(self, sensor_stream=None):
        self.sensor_stream = sensor_stream or Stream(asynchronous=True)
        self._server = None
        self._server_task = None
        self.logger = get_logger("SensorProbe")
        self.encoder = None
        self.scaler = None
        self.features_to_keep = SENSOR_FEATURE_LIST
        self.data_counter = 0
        self._lock = threading.Lock()
        self.detect_stream = self.sensor_stream.map(self._parse_sensor_data)
        self.logger.info("SensorProbe initialized.")


    def _parse_sensor_data(self, b: bytes):
        s = b.rstrip(b"\n").decode("utf-8", "replace")
        if not s:
            return None

        try:
            js_dict = json.loads(s)
            # --- KEY VALIDATION (only enforce required keys) -------------------------
            incoming_keys = js_dict.keys()

            missing = [k for k in SENSOR_FEATURE_LIST if k not in incoming_keys]

            if missing:
                raise KeyError(f"Missing required sensor features: {missing}")
            
            with self._lock:
                sensor_data_scaled = self.scale_data(js_dict)
        
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                log = {'dat[SENSOR_FEATURE_LIST]a_count': self.data_counter}

                sensor_data_package = cSensorData(
                    EDGE_DEVICE_ID,
                    timestamp,
                    sensor_data_scaled[0].tolist(),
                    log
                )
                self.data_counter += 1
                return sensor_data_package.to_json()

        except Exception as e:
            print(f"[JSON ERROR] {e} :: {s[:200]}")
            self.logger.exception(f"[JSON ERROR] {e} :: {s[:200]}")
            return None
    
    def scale_data(self, js_dict: dict):
        js_df = pd.DataFrame([js_dict])[SENSOR_FEATURE_LIST]

        scaled_array = self.scaler.transform(js_df)

        return scaled_array
    
    # def _extract_features(self, js: dict):
    #     """
    #     Select only the sensor features defined in SENSOR_FEATURE_LIST
    #     and return their values in the same order.
    #     Missing features are replaced with 0.0 (or np.nan if preferred).
    #     """
    #     features = []
    #     for key in SENSOR_FEATURE_LIST:
    #         value = js.get(key, 0.0)  # or np.nan if you want to mark missing values
    #         try:
    #             features.append(float(value))
    #         except (ValueError, TypeError):
    #             features.append(0.0)  # fallback if value is non-numeric
    #     return features

    async def create_tcp_server(self, host=TCP_HOST_IP, port=SENSOR_DATA_TCP_PORT):
        async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                while True:
                    line = await reader.readline()  # reads until b"\n" or EOF
                    if not line:
                        break
                    # IMPORTANT: in async mode, emit returns an awaitable — await it
                    # print(f"[DEBUG] Received sensor data: {line}")
                    await self.sensor_stream.emit(line)    # backpressure-friendly
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
        
        server = await asyncio.start_server(_handle_client, host, port)
        # print(f"TCP server listening on {host}:{port}")
        self.logger.info(f"TCP server listening on {host}:{port}")
        
        async with server:
            await server.serve_forever()

    def load_sensor_scaler(self):
        """
        Loads the sensor scaler object from the predefined SENSOR_SCALER.
        """
        try:
            self.scaler = joblib.load(SENSOR_SCALER)
            return None
        except Exception as e:
                self.logger.exception(e)



