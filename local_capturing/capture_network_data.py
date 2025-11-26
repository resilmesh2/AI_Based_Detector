
from __future__ import annotations

import argparse
import json
import logging
import time
import os
import sys
from typing import Any, Dict, Optional

from nfstream import NFStreamer  # type: ignore

from utils import (
    ContainerInfo,
    connect_with_retry,
    env_int,
    env_str,
    resolve_container_ip,
    send_jsonl,
    setup_logging,
    flow_to_dict,
)


# --- configure logging from VERBOSE in .env ---
setup_logging(env_int("VERBOSE", 0))
log = logging.getLogger("capture_network")



# -------------------------------------------------------------------
# Load .env automatically (python-dotenv, fallback manual)
# -------------------------------------------------------------------
def load_env_file():
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(".env", override=False)
    except Exception:
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# -------------------------------------------------------------------
# Main entry
# -------------------------------------------------------------------
def main():
    load_env_file()

    # Configure logging
    setup_logging(env_int("VERBOSE", 0))
    log = logging.getLogger("capture_network")

    # Require root for pcap access / NFStreamer
    if os.geteuid() != 0:
        sys.stderr.write("[ERROR] This script must be run as root (use sudo).\n")
        sys.exit(1)

    # -------------------------------------------------------------------
    # Configuration via environment variables
    # -------------------------------------------------------------------
    container_name = env_str("CONTAINER_NAME", "ai-ad")
    dest_host      = env_str("DEST_HOST_IP")
    dest_port      = env_int("NETWORK_DEST_PORT", 9000)

    # Default to loopback for simulation
    iface = env_str("IFACE", "lo")

    # Resolve container IP if DEST_HOST_IP is unset
    if not dest_host:
        container_info: Optional[ContainerInfo] = resolve_container_ip(container_name)
        if not container_info:
            raise SystemExit("Failed to resolve container IP. Is it running?")
        dest_host = container_info.ip

    # Connect to TCP receiver with retry logic
    sock = connect_with_retry(dest_host, dest_port)
    log.info(f"Connected to {dest_host}:{dest_port}; capturing on interface '{iface}'...")

    # -------------------------------------------------------------------
    # NFStreamer configuration
    # -------------------------------------------------------------------
    streamer = NFStreamer( source=iface, idle_timeout=5, 
                          active_timeout=60, splt_analysis=1, 
                          statistical_analysis=True, # max_nflows=5, 
                          )

    # -------------------------------------------------------------------
    # Stream → Convert → Send
    # -------------------------------------------------------------------
    for flow in streamer:
        try:
            payload = flow_to_dict(flow)
            #print("-----------------------")
            #print(payload)
            #print("-----------------------")
     

            log.debug(
                f"flow-{payload.get('id')} | "
                f"{payload.get('application_name')} | "
                f"{payload.get('application_category_name')}"
            )

            send_jsonl(sock, payload)

        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            log.warning(f"Socket error ({e}). Reconnecting ...")
            sock.close()
            sock = connect_with_retry(dest_host, dest_port)

        except Exception as e:
            log.exception(f"Failed to serialize/send flow: {e}")
            continue

    # Gentle pacing (NFStreamer manages timing internally)
    time.sleep(1)


# -------------------------------------------------------------------
# Run directly
# -------------------------------------------------------------------

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted by user. Exiting.")
