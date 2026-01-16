# Data preparation for Anomaly Detection

This project provides an anomaly detection framework with network as well as sensor data

---

## Description

In this project we capture the network traffic using the NFStream python module, create sensor data from a csv file and publish them to an anomaly detector via TCP. For simulating live network traffic we use tcpreplay to convert pcap files into live network traffic

---

## Features

* **Key Feature 1:** Simulate traffic via tcpreplay
* **Key Feature 2:** Capture network traffic via NFStream
* **Key Feature 3:** Create artificial sensor dat.

---

## Getting Started

### Prerequisites

List all the necessary software, dependencies, and their specific versions required to run the project.

* `tcpreplay`: 4.4.4 (Compiled against libpcap: 1.10.4, follow the instructions on https://tcpreplay.appneta.com/wiki/installation.html)
* `nfstream`: 6.5.3
* `pandas`: 2.3.1


### SETUP of important configs
This project uses a `.env` file to manage environment-specific settings.
Below is a list of the key variables you need to configure:

| Variable | Description | Default Value |
| :--- | :--- | :--- |
| `CSV_PATH` | The path to the csv file that contains the artifical sensor data. | `./data/BATADAL_testdataset_copy.csv` |
| `CONTAINER_NAME` | Docker container id if anomaly detector runs inside docker. | `resilmesh-tap-ai-ad` |
| `DEST_HOST_IP` | This should only be used if AD is running locally. | Not exisiting or `localhost` |
| `SENSOR_DEST_PORT` | The TCP port for sensor data communication. | `9001` |
| `NETWORK_DEST_PORT` | The TCP port for network data communication. | `9000` |
| `VERBOSE` | Log output level. | `0` for no console output, `>0` console output |
| `IFACE` | This is the network interface for tcpreplay and nfstream. | `enp0s31f6` |
| `PCAP_FILE` | The pcap file for simulating the network traffic with tcpreplay. | `pcap_files/capture_tiny.pcap` |

### How to run everything


A Makefile is provided to facilitate the launching of all three tasks:
network traffic simulation, network data capturing, and sensor data creation.

Before you begin, ensure you have the necessary dependencies installed.
Then, you can use the following commands:

1.  **To see available options:**

    ```bash
    make help
    ```

2.  **To simulate network traffic:**

    ```bash
    make simulate_network_traffic
    ```

3.  **To capture network data (requires `sudo`):**

    ```bash
    make network_data_capturing
    ```

4.  **To create sensor data:**

    ```bash
    make sensor_data_creation
    ```

