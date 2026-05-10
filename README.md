# Robotic Beekeeper
Bachelor's thesis at Brno University of Technology, Faculty of Information Technology (VUT FIT), 2025/2026.

**Author:** Eliška Křeménková (xkremee00)\
**Supervisor:** doc. RNDr. Pavel Smrž, Ph.D.

## Overview

An automated beehive monitoring system consisting of two hardware nodes and a server:

- **Sensor node (ESP32-S3)** - measures hive weight, outdoor temperature, and indoor temperature, humidity, and pressure, publishes readings to an MQTT broker every 5 minutes
- **Camera node (Raspberry Pi 5)** - detects and counts bees at the hive entrance using a YOLO11n model with ByteTrack tracking, distinguishes bees carrying pollen and direction of movement
- **Server (Raspberry Pi 4)** - receives all data via MQTT, stores it in a SQLite database, runs anomaly detection using LightGBM predictions, and visualises everything in Grafana with email alerts

## Repository Structure

```
.
├── data/
│   ├── BeeObserver/          # BeeObserver (BoB) dataset used for model training
│   │   └── {year}/49.csv
│   ├── sensor_data.csv       # Real sensor readings from the deployment period
│   └── bee_count_log.csv     # Real bee traffic counts from the deployment period
│
├── docs/
│   ├── installation_guide.md # Step-by-step setup for all nodes and the server
│   ├── user_manual.md        # How to use and monitor the system
│   └── schematic.png         # Sensor node wiring schematic
│
├── src/
│   ├── firmware/
│   │   ├── beehive.ino       # ESP32-S3 Arduino sketch
│   │   └── config.h.example  # WiFi and MQTT credentials template
│   │
│   ├── scripts/
│   │   ├── bee_counter.py                  # Camera node - real-time bee counting
│   │   ├── subscriber.py                   # Server - MQTT subscriber and database writer
│   │   ├── forecast_anomaly_detection.py   # Server - hourly prediction and anomaly detection
│   │   ├── photo_script.py                 # Utility - time-lapse photo capture (dataset collection)
│   │   └── config.py.example               # MQTT configuration template
│   │
│   ├── models/
│   │   ├── machine_learning.ipynb                      # Model training notebook (LightGBM + LSTM)
│   │   ├── lgb_separate_weight-delta-noOutlier.txt     # Trained LightGBM weight model
│   │   ├── lgb_separate_t-i-3.txt                      # Trained LightGBM temperature model
│   │   ├── lgb_feature_cols.json                       # Feature column list for inference
│   │   └── mybeesyolo11.ncnn.zip                       # YOLO11n bee detection model (NCNN format)
│   │
│   ├── config/
│   │   ├── beehive.conf                    # Mosquitto broker configuration
│   │   ├── beehive-subscriber.service      # systemd service for the subscriber script
│   │   ├── contrab.example                 # Cron entry for forecast_anomaly_detection.py
│   │   ├── grafana.ini.smtp.example        # Grafana SMTP email alert configuration template
│   │   └── Beekeeper5_grafana_export.json  # Grafana dashboard export
│   │
│   └── 3d_models/                          # SolidWorks parts and assembly for the hive scale and camera module
│
├── tex_src/                  # LaTeX source files for the thesis
├── plakat.pdf                # Project poster
├── requirements.txt          # Python dependencies
├── LICENSE
└── README.md
```

## Data

### Deployment Data

Real sensor and camera data collected during the deployment period (April–May 2026):
- `data/sensor_data.csv` - weight, temperatures, humidity, pressure (5-minute intervals)
- `data/bee_count_log.csv` - individual bee crossing events with direction and class
Both files were exported from the SQLite database on the Raspberry Pi 4.

### Training Data

The LightGBM and LSTM models were trained on the **BeeObserver (BoB)** dataset - sensor data from instrumented honey bee colonies recorded in Germany between 2019 and 2022. Colony 49 is used across all four available years.

Dataset source: [BeeObserver on Zenodo](https://zenodo.org/records/10407693)

## Quick Start

See [`docs/installation_guide.md`](docs/installation_guide.md) for full step-by-step instructions for all three nodes and the server.

### Sensor Node (ESP32-S3)

1. Install Arduino IDE and required libraries (see installation guide)
2. Copy `src/firmware/config.h.example` to `src/firmware/config.h` and fill in credentials
3. Flash `src/firmware/beehive.ino`

### Camera Node (Raspberry Pi 5)

1. Create a virtual environment with system-wide packages and install dependencies
2. Copy `src/scripts/config.py.example` to `src/scripts/config.py` and fill in credentials
3. Unzip the YOLO model to `~/Desktop/beehive/`
4. Run `python3 src/scripts/bee_counter.py`

### Server (Raspberry Pi 4)

1. Install Mosquitto, SQLite, and Grafana (see installation guide)
2. Start the subscriber as a systemd service
3. Add the cron job for anomaly detection
4. Import the Grafana dashboard from `src/config/Beekeeper5_grafana_export.json`

## Model Training

The `src/models/machine_learning.ipynb` notebook contains the full training pipeline:
- Data loading and feature engineering from the BeeObserver dataset
- LightGBM training (separate models for weight delta and internal temperature)
- LSTM training as a comparison model
- Anomaly detection evaluation
Run from the repository root with the `data/BeeObserver/` directory present.

## License

See [`LICENSE`](LICENSE).





