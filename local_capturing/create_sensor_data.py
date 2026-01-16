# sensor_sender.py
"""
Read sensor data from CSV and stream rows as JSON arrays over TCP.

Requirements:
  pip install pandas

Usage examples:
  python sensor_sender.py --csv data/BATADAL_testdataset_copy.csv --container resilmesh-tap-ai-ad --port 9001
  CSV_PATH=./data/BATADAL_testdataset_copy.csv CONTAINER_NAME=resilmesh-tap-ai-ad DEST_PORT=9001 python sensor_sender.py
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from typing import List, Optional

import pandas as pd  # type: ignore

from utils import (
    ContainerInfo,
    connect_with_retry,
    env_int,
    env_str,
    resolve_container_ip,
    send_jsonl,
    setup_logging,
)


try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(".env", override=False)
except Exception:
    # minimal fallback parser
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                key, val = s.split("=", 1)
                key, val = key.strip(), val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)

# --- configure logging from VERBOSE in .env ---
verbose_level = env_int("VERBOSE", 0)  # VERBOSE=0,1,2,...
setup_logging(verbose_level)
log = logging.getLogger("sensor_sender")

def read_sensor_csv(file_path: str):
    """
    Load CSV and return DataFrame with only model['flow_features'] + attack label.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No file found at {file_path}")

    df = pd.read_csv(file_path)
    return df


def main():
    # --- config via env ---
    csv_path = env_str("CSV_PATH", "data/BATADAL_testdataset_copy.csv")
    dest_host = env_str("DEST_HOST_IP")
    container_name = env_str("CONTAINER_NAME", "resilmesh-tap-ai-ad")
    dest_port = env_int("SENSOR_DEST_PORT", 9001)
    row_delay_sec = float(env_str("ROW_DELAY_SEC", "3.0"))

    # Resolve container IP if host not given
    if not dest_host:
        container_info: ContainerInfo | None = resolve_container_ip(container_name)
        if not container_info:
            raise SystemExit("Failed to resolve container IP. Is it running?")
        dest_host = container_info.ip

    # Load CSV
    try:
        df = read_sensor_csv(csv_path)
    except Exception as e:
        log.error("Failed to load CSV: %s", e)
        raise SystemExit(1)

    if df.empty:
        log.error("CSV loaded but contains no rows after filtering.")
        raise SystemExit(1)

    # Connect
    sock = connect_with_retry(dest_host, dest_port)
    log.info("Starting to process and send %d rows ...", len(df))

        # Stream rows
    for idx, row in df.iterrows():
        try:
            # Convert row to dict, excluding label if needed
            row_dict = row.to_dict()
            # row_dict.pop('attack', None)  # optional, if you want to drop label column

            # Convert values to serializable forms
            for key, value in row_dict.items():
                if isinstance(value, (pd.Timestamp, )):
                    # Convert pandas timestamps to ISO format
                    row_dict[key] = value.isoformat()
                elif isinstance(value, (float, int, str)):
                    # Already serializable
                    continue
                else:
                    try:
                        row_dict[key] = float(value)
                    except (ValueError, TypeError):
                        # Fallback to string representation
                        row_dict[key] = str(value)

            # Send as JSON line
            send_jsonl(sock, row_dict)

            log.debug("Row %s sent (%d keys).", idx, len(row_dict))

        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            log.warning("Socket error (%s). Reconnecting ...", e)
            sock.close()
            sock = connect_with_retry(dest_host, dest_port)
            continue
        except Exception as e:
            log.exception("Failed to process/send row %s: %s", idx, e)
            continue

            time.sleep(row_delay_sec)

    log.info("All rows sent.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted by user. Exiting.")
