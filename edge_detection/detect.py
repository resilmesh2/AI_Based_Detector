import os
import json
import logging
import asyncio
from functools import partial
from collections import deque
from datetime import datetime

import torch
import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from streamz import Stream
import nats
from paho.mqtt.client import Client
from dotenv import load_dotenv

from network_capturing.probe import NetworkProbe, SensorProbe
from models_server.ae_models import NetworkAutoEncoder, SensorAutoEncoder
from models_server.data_scheme import (
    NetworkBundle, SensorBundle, NetworkAnomalies, NetworkModel,
    SensorAnomalies, SensorModel, ReplayBuffer
)
from models_server.data_config import (
    DEFAULT_RELATIONSHIP, DEFAULT_SENSOR_MODEL, DEFAULT_SENSOR_ANOMALY,
    DEFAULT_NETWORK_MODEL, DEFAULT_NETWORK_ANOMALY
)
from logging_setup import get_logger
# Load environment variables from .env file in the main script directory
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, "..", ".env")
load_dotenv(env_path)

EDGE_DEVICE_ID   = os.getenv("EDGE_DEVICE_ID")
LOG_PATH         = os.getenv("LOG_PATH")
EDGE_DETECTOR    = os.getenv("EDGE_DETECTOR")
NETWORK_FILE     = os.getenv("NETWORK_FILE")
SENSOR_FILE      = os.getenv("SENSOR_FILE")
SENSOR_MODEL     = os.getenv("SENSOR_MODEL")
SENSOR_SCALER    = os.getenv("SENSOR_SCALER")
NETWORK_MODEL    = os.getenv("NETWORK_MODEL")
NETWORK_SCALER   = os.getenv("NETWORK_SCALER")
VECTOR_URL       = os.getenv("VECTOR_URL")
NATS_SERVER      = os.getenv("NATS_SERVER")
NETWORK_SUBJECT  = os.getenv("NETWORK_SUBJECT")
SENSOR_SUBJECT   = os.getenv("SENSOR_SUBJECT")

#from confluent_kafka import Producer
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

class cEdgeDetector:
    def __init__(self, NetworkStream: Stream, SensorStream: Stream, MQTTClient: Client):
        """Initialize with a Streamz Stream object."""
        self.NetworkStream = NetworkStream
        self.SensorStream = SensorStream
        self.MQTTclient = MQTTClient
        self.cNetworkAutoencoder = NetworkAutoEncoder().to(device=device) 
        self.NetworkCriterion = torch.nn.MSELoss(reduction='mean') 
        self.oNetworkScaler = None
        self.oNetworkBundle = NetworkBundle(
                                            type="bundle",
                                            id="bundle--cd2a2cf9-18f3-480a-aaa5-c4b59ce6910b",
                                            objects=[
                                                NetworkAnomalies(**DEFAULT_NETWORK_ANOMALY    
                                                ),
                                                NetworkModel(**DEFAULT_NETWORK_MODEL  
                                                )
                                            ]
                                        )
        
        self.cSensorAutoencoder = SensorAutoEncoder().to(device=device) 
        self.oSensorScaler = None
        self.oSensorBundle = SensorBundle(
                                        type="bundle",
                                        id="bundle--cd2a2cf9-18f3-480a-aaa5-c4b59ce6910b",
                                        objects=[
                                            SensorAnomalies(**DEFAULT_SENSOR_ANOMALY   
                                            ),
                                            SensorModel(**DEFAULT_SENSOR_MODEL  
                                            )
                                        
                                        ]
                                    )

        self.NetworkBuffer = ReplayBuffer(capacity=10)
        self.SensorBuffer = ReplayBuffer(capacity=10)
        self.dSensorRecErr = deque(maxlen=7)  # Keeps the last 7 reconstruction errors
        self.logger = get_logger("cEdgeDetector")
        self.logger.info("cEdgeDetector initialized.")

    def setup_network_stream(self, network_probe: NetworkProbe, thres_network, send_network_feat):
        """Setup processing pipeline."""
        network_probe.detect_stream.map(partial(self.detect_network_anomaly, fThresNetwork=thres_network, bNetworkFeatures=send_network_feat))\
        .sink(self.nats_emit_network) 

    def setup_sensor_stream(self, sensor_probe: SensorProbe, thres_sensor, send_sensor_feat):
        """Setup processing pipeline."""
        sensor_probe.detect_stream.map(partial(self.detect_sensor_anomaly, fThresSensor=thres_sensor, bSensorFeatures=send_sensor_feat))\
        .sink(self.nats_emit_sensor) 

    def nats_emit_network(self, oResultNetworkBundle):
        """Synchronous function that reads JSON and sends data to NATS."""
        try:
            # print(f"nats_emit_network: Network anomaly detected: {oResultNetworkBundle.get_objects(0, 'label')}")
            if oResultNetworkBundle.get_objects(0, "label") == "network_anomaly":
                ##########################
                # pull back values to ensure consistency
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                label = oResultNetworkBundle.get_objects(0, "label")
                value = oResultNetworkBundle.get_objects(0, "value")
                severity = self.oNetworkBundle.get_objects(0, "severity")
                if True:
                    include_flow = False  # <-- set this dynamically as needed
                    if include_flow:
                        flow_data = oResultNetworkBundle.get_objects(0, "flow_data")
                        self.logger.debug(f"Label: {label} | Value: {value:.7f} | Severity: {severity} | Flow Data:{flow_data}")
                    else:
                        # print(f"[{timestamp}] Label: {label} | Value: {value:.7f} | Severity: {severity}")
                        self.logger.debug(f"Label: {label} | Value: {value:.7f} | Severity: {severity}")
                ##########################
                payload = oResultNetworkBundle.to_json()
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.publish_to_nats(payload, NETWORK_SUBJECT))
                else:
                    loop.run_until_complete(self.publish_to_nats(payload, NETWORK_SUBJECT))
        except Exception as e:
            self.logger.exception(f"Error in nats_emit_network: {e}")


    def nats_emit_sensor(self, oResultSensorBundle):
        """Synchronous function that reads JSON and sends data to NATS."""
        try:
            if oResultSensorBundle.get_objects(0, "label") == "sensor_anomaly":
                ##########################
                # pull back values to ensure consistency
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                label = oResultSensorBundle.get_objects(0, "label")
                value = oResultSensorBundle.get_objects(0, "value")
                severity = oResultSensorBundle.get_objects(0, "severity")
                if True:
                    include_flow = False  # <-- set this dynamically as needed 
                    if include_flow:
                        flow_data = oResultSensorBundle.get_objects(0, "flow_data")
                        # print(f"[{timestamp}] Label: {label} | Value: {value:.7f} | Severity: {severity} | Flow: {flow_data}")
                        self.logger.debug(f"Label: {label} | Value: {value:.7f} | Severity: {severity} | Flow: {flow_data}")
                    else:
                        # print(f"[{timestamp}] Label: {label} | Value: {value:.7f} | Severity: {severity}")
                        self.logger.debug(f"Label: {label} | Value: {value:.7f} | Severity: {severity}")
                ##########################
                payload = oResultSensorBundle.to_json()
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.publish_to_nats(payload, SENSOR_SUBJECT))
                else:
                    loop.run_until_complete(self.publish_to_nats(payload, SENSOR_SUBJECT))
        except Exception as e:
            print(f"Error in nats_emit_sensor: {e}")
            self.logger.exception("Error in nats_emit_sensor: %s", e)

    async def publish_to_nats(self, data, subject):
        """Async function to publish messages to NATS."""
        # return
        try:
            data_str = data.decode('utf-8', errors='ignore')
            # Create a shortened preview of the data
            preview = data_str[:80] + '...}' if len(data_str) > 80 else data_str
            nc = await nats.connect(NATS_SERVER)
            await nc.publish(subject, data)  # ensure data is bytes
            #print(f"Published to '{subject}': {preview}")
            #print("__________________________________________________")
            # print(f"Published to '{subject}': {data}")
            await nc.flush()
            await nc.close()
        except Exception as e:
            print(f"Error in publish_to_nats: {e}")
            self.logger.exception("Error in publish_to_nats: %s", e)

    def detect_network_anomaly(self, data_instance, fThresNetwork, bNetworkFeatures):
        """
        Processes a single data instance through the autoencoder.
        
        Parameters:
            data_instance (Data): The data instance (from Data generator Network stream).

        Returns:
            a Anomly score in the predefined event format
        """
        try:
            # Convert JSON string back to dictionary
            data_dict = json.loads(data_instance)
            
            SCR_IP = data_dict["src_ip"]
            DST_IP = data_dict["dst_ip"]
            SRC_PORT = data_dict["src_port"]
            DST_PORT = data_dict["dst_port"]
            PROTOCOL = data_dict["protocol"]
            
            self.NetworkBuffer.append(data_dict["features"])
            
            #    data_dict["src_ip"]
            #     data_dict["dst_ip"]  

            # print(f"features retrieved: {data_dict['features']}")
            lDataList = data_dict["features"]
            lDataArray= np.array(lDataList).reshape(1, -1)

            #ScaledDataArray  = self.oNetworkScaler.transform(lDataArray)
            DataTensor = torch.tensor(lDataArray, dtype=torch.float32, device=device)
            iResult = 0
            sAnomaly = "normal"
            fRecError = None
            sSeverity = " "
            if len(lDataList) != 0:
                self.NetworkBuffer.append(lDataList)
                recDataTensor = self.cNetworkAutoencoder(DataTensor)
                iResult, fRecError = self.calculate_rec_error(DataTensor, recDataTensor, fThresNetwork)


              
                print(f"iResult: {iResult}, fRecError: {fRecError:.8f} of {data_dict['log']['flow_count']}-th")
                print("__________________________________________________")
            
            if iResult == 1:
                sAnomaly = "network_anomaly"
                sSeverity = self.calculate_severity(fRecError, fThresNetwork)

            if bNetworkFeatures:
                network_buffer = self.NetworkBuffer.get_buffer()  # Retrieve buffer
                features = network_buffer[-1] if network_buffer else []  # Safe last element access
            else: 
                features = []

            #print(iResult, fRecError)
            self.oNetworkBundle.set_objects(0, "flow_data", features)
            self.oNetworkBundle.set_objects(0, "label", sAnomaly)
            self.oNetworkBundle.set_objects(0, "value", fRecError)
            self.oNetworkBundle.set_objects(0, "severity", sSeverity)
            self.oNetworkBundle.set_objects(0, "source_ip", SCR_IP)
            self.oNetworkBundle.set_objects(0, "destination_ip", DST_IP)
            self.oNetworkBundle.set_objects(0, "source_port", SRC_PORT)
            self.oNetworkBundle.set_objects(0, "destination_port", DST_PORT)
            self.oNetworkBundle.set_objects(0, "protocol", PROTOCOL)            
            # Debug print for the network bundle
            
        except Exception as e:
            print(f"An error occurred in detect_network_anomaly: {e}")
            # Log the exception including type, script name, and line number
            self.logger.exception(e)
        oNetworkBundle = self.oNetworkBundle
    
        return oNetworkBundle
    
    def detect_sensor_anomaly(self, data_instance, fThresSensor, bSensorFeatures):
        try:
            # Convert JSON string back to dictionary
            data_dict = json.loads(data_instance)
            device_id = data_dict["device_id"]
            timestamp = data_dict["timestamp"]
            lDataList =  data_dict["features"]

            # you can fill in other flow info here
            iResult = 0
            sAnomaly = "normal"
            sSeverity = " "
            fRecError = None
            if len(lDataList) != 0: # to filter out the heartbeat stream from the sensor data stream
                # Convert the list to a 2D array (required by the scaler)
                lDataArray= np.array(lDataList).reshape(1, -1) # Reshape to 2D array: (5, 1)
                # Apply the scaler to the list
                # ScaledDataArray  = self.oSensorScaler.transform(lDataArray)
                # DataTensor = torch.tensor(ScaledDataArray, dtype=torch.float32, device=device)
                DataTensor = torch.tensor(lDataArray, dtype=torch.float32, device=device)
                self.SensorBuffer.append(lDataList)

                recDataTensor = self.cSensorAutoencoder(DataTensor)
                _, fRecError = self.calculate_rec_error(DataTensor, recDataTensor, fThresSensor)
                self.dSensorRecErr.append(fRecError)

                iResult, avgRecError = self.is_anomaly(fThresSensor)


                
                #print(f"iResult: {iResult}, fRecError: {fRecError:.8f} of {data_dict['log']['data_count']}-th data: {lDataList}")

                if iResult == 1:
                    sAnomaly = "sensor_anomaly"
                    sSeverity = self.calculate_severity(avgRecError, fThresSensor)
            else:
                iResult = -1
                sAnomaly = 'heartbeat'
                fRecError = -10.
            
            if bSensorFeatures:
                sensor_buffer = self.SensorBuffer.get_buffer()  # Retrieve buffer
                features = sensor_buffer[-1] if sensor_buffer else []  # Safe last element access
            else: 
                features = []

            self.oSensorBundle.set_objects(0, "flow_data", features)
            self.oSensorBundle.set_objects(0, "label", sAnomaly)
            self.oSensorBundle.set_objects(0, "value", fRecError)
            self.oSensorBundle.set_objects(0, "severity", sSeverity)

            ## we need the moving average and the threshold
            ## we need to add in the emmission function the "heartbeat"
            
        except Exception as e:
            exit(0)
            # Log the exception including type, script name, and line number
            self.logger.exception(e)
        oSensorBundle = self.oSensorBundle
    
        return oSensorBundle
       
    def is_anomaly(self, fThresSensor):
        """
        Calculate the moving average of the last 7 reconstruction errors and
        return 1 if the average is greater than fThresSensor, otherwise return 0.
        """
        moving_average_error = None
        if len(self.dSensorRecErr) > 0:
            moving_average_error = np.mean(self.dSensorRecErr)
            # Compare the moving average with the threshold
            if moving_average_error > fThresSensor:
                return 1, moving_average_error
            else:
                return 0, moving_average_error
        else:
            return 0, moving_average_error  
    
    def calculate_severity(self, rec_error, threshold):
        severity = "low"
        if rec_error >= 10*threshold:
            severity = "high"
        return severity

    def calculate_rec_error(self, x, x_hat, threshold):
        with torch.no_grad():
            # mean over features only
            mse = torch.mean((x_hat - x) ** 2, dim=1)
            val = float(mse.item())
            anomaly = int(val > threshold)
            return anomaly, val
    
    def load_sensor_state_dict(self):
        try:
            self.cSensorAutoencoder.load_state_dict(torch.load(SENSOR_MODEL, map_location=torch.device('cpu')))
            self.cSensorAutoencoder.eval()
            return None
        except Exception as e:
            self.logger.exception(e)
    def load_sensor_scaler(self):
       # Load the scaler object from the file
        try:
            self.oSensorScaler = joblib.load(SENSOR_SCALER)
            return None
        except Exception as e:
                self.logger.exception(e)

    def load_network_state_dict(self):
        try:
            self.cNetworkAutoencoder.load_state_dict(torch.load(NETWORK_MODEL, map_location=device))
            self.cNetworkAutoencoder.eval()
            return None
        except Exception as e:
            self.logger.exception(e)



if __name__ == '__main__':

       
    # Load the scaler object from the file
    oSensorScaler = joblib.load(SENSOR_SCALER)

    testArray = np.array([0.18782193, 0.55160605, 0.37169323, 0.59530061, 0.02395982, 0.98507509,
                0.65452466, 0.37836948, 0.16107924, 0.15495709, 0.28417575, 0.61170494,
                0.17910644, 0.69431589, 0.96056981, 0.04073757, 0.3442462 , 0.37976062,
                0.96699848, 0.49585521, 0.81699079, 0.77777401, 0.6149702 , 0.73113961,
                0.51517336, 0.59396699, 0.16492255, 0.13990838, 0.68191866, 0.06784236,
                0.29118052, 0.92323094, 0.89659095, 0.10734797, 0.9112083 , 0.0732573 ,
                0.48753991, 0.16911605, 0.12847717, 0.52943054, 0.12403683, 0.81159002,
                0.67479697]
                )

    scaledArray = oSensorScaler.transform(testArray)
    print(scaledArray)
#     file_path = '/Users/michiundslavki/Dropbox/JR/SerWas/cyber_attack_edge_2/edge_device/data/BATADAL_dataset03.csv'
#     df = pd.read_csv(file_path)
#     sliced_df = df.iloc[10,1:-1]
#     BADATAL_list = sliced_df.to_list()
#     #data_instance = {'device_id': 'device4_2060', 'features': BADATAL_list, 'log': {'temperature': 29, 'status': 'normal'}}
#     device_id = "EDGE_DEVICE_ID"
#     current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
#     pressure = random.uniform(10, 100)  # Simulate pressure in psi
#     temperature = random.uniform(-20, 100)  # Simulate temperature in Celsius
#     log = "Normal" if random.random() > 0.1 else "Error: Pressure too high"
#     data_instance = cSensorData(device_id=device_id, timestamp=current_time, pressure=pressure, temperature=temperature, log=log)
#     NetworkStream = Stream()
#     SensorStream = Stream()
#     oAutoencoder = BADATALAutoEncoder()
#     oEdgeDetctor = cEdgeDetector(NetworkStream, SensorStream, oAutoencoder)
#     #print(data_instance['id'])
#     SensorStream.emit(data_instance)
#     #oEdgeDetctor.detect_anomaly(data_instance, 0.07)
#     #oEdgeDetctor.output_results(bSend_Features=False)

# ### TO DOS ###
#     # make emit_senor data function
#     # - adjust stream up 
#     # - define a scheme for Sensor Reslut?
#     #  - change the out put functions and test them

  
    # def detect_network_anomaly(self, data_instance, fThresNetwork, bNetworkFeatures):
    #     """
    #     Processes a single data instance through the autoencoder.
        
    #     Parameters:
    #         data_instance (Data): The data instance (from Faust stream).

    #     Returns:
    #     """
    #     try:

            


    #         device_id = data_instance.device_id # data_instance['id'] #data_instance.id 
    #         timestamp = data_instance.timestamp
    #         _type = 'network'
    #         self.NetworkBuffer.append(data_instance.features)
    #         lDataArray = data_instance.features
    #         dLogDict = dict()
    #         dDetectDict = dict()

    #         iResult = -1
    #         ####### for ilustrative purpose
    #         lDataArray = [random.random() for i in range(0,51)]
    #         if len(data_instance.features) != 0: # to filter out the heartbeat stream from the sensor data stream
    #             self.NetworkBuffer.append(data_instance.features)
    #             iResult = self.cNetworkAutoencoder.inference(lDataArray, fThresNetwork)
    #             print(iResult)
    #         # ####### for ilustrative purpose
    #         # rand = random.random()
    #         # if rand > 0.8:
    #         #     iResult = int(1)
    #         # else:
    #         #     iResult = int(0)
    #         # ########
    #         if bNetworkFeatures:
    #             features = self.NetworkBuffer.get_buffer()
    #         else: 
    #             features = []
    #         detection_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    #         dLogDict['detection_time'] = detection_time
           
    #         oResultDataNetwork = cNetworkResult(device_id, timestamp, _type, iResult, features, dLogDict)
            
    #         if (data_instance.log['label'] > 0) or (iResult > 0):
    #             dDetectDict['edge_id'] = EDGE_DEVICE_ID
    #             dDetectDict['_type'] = _type
    #             dDetectDict['timestamp'] = timestamp
    #             dDetectDict['true_label'] = data_instance.log['label']
    #             dDetectDict['det_timepstamp'] = detection_time
    #             dDetectDict['det_label'] = iResult
    #             # Write the header only if it's the first line
    #             if self.csv_line == 0:
    #                 self.csv_writer.writerow(dDetectDict.keys())
    #             # Write the data
    #             self.csv_writer.writerow(dDetectDict.values())
    #             # Increment the line counter
    #             self.csv_line += 1

    #     except Exception as e:
    #         # Log the exception including type, script name, and line number
    #         self.logger.exception(e)

    #     return oResultDataNetwork
