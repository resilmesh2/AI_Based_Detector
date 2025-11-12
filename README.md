this is the Anomlay detction container part of the ResilMesh framework


/Anomaly_Detector/.env

there the locations of the Model (Pytorch) and the scaler and the encoder paths are specifed where the trained and fitted versions need to be postions

the Model [text](models_server/ae_models.py) atchitecture is specified there

Anomaly_Detector/models_server/data_config.py there you can speficy the network and sensor data features that where specfiedfe in training. and you can add model specs form the training like perforemcan etc.

then the pipline

we hava network probe

there is a local part of this for this refer to the local_capturing folder. insatll pyhton 3.11 nfstream version??


2.  **To simulate network traffic:**

    ```bash
    make simulate_network_traffic
    ```

3.  **To capture network data (requires `sudo`):**

    ```bash
    make network_data_capturing
    ```

then the part inside the container Anomaly_Detector/network_capturing it listen to a tcp port from the local part and it takes the flows and preocosses them, selects based on the NETWORK_FEATURE list and encodes and sacle the them and emits them to the streamz streaming pipline. 

Then the second part is the dection (/home/digital/Documents/RM-WP4_network_capturing/Anomaly_Detector/edge_detection) it takes in the preprocced network flow and dtectes anomlies via the trained Autoencoder and appends necessarey information to predfiend scheme (specidei in models_server/data_config.py ) and then publishes the result to the NATS sevrer in the NATS contierna ad_events subject. 

Then it flowws the framework path through until reuslting in an standardized event in Wazuh.