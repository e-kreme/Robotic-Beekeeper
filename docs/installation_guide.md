# Installation Guide

## Sensor Node (ESP32-S3)

### Prerequisites

- 64-bit Linux system
- USB-C cable capable of data transfer (not charge-only)
- LilyGO TTGO T-Display-S3 board

### Install Arduino IDE

- Download `arduino-ide_2.3.8_Linux_64bit.AppImage` from the official Arduino website: https://www.arduino.cc/en/software
- Make it executable:
  ```bash
  chmod +x arduino-ide_2.3.8_Linux_64bit.AppImage
  ```
- Run it:
  ```bash
  ./arduino-ide_2.3.8_Linux_64bit.AppImage
  ```

### Serial Port Permissions

- Add your user to the `dialout` group:
  ```bash
  sudo usermod -aG dialout $USER
  ```
- Log out and back in for the change to take effect
- Without this step, Arduino IDE will not be able to access the serial port
- For more information see: https://support.arduino.cc/hc/en-us/articles/360016495679-Fix-port-access-on-Linux

### Add ESP32 Board Support

- Open **File → Preferences**
- Add the following URL to the **Additional boards manager URLs** field:
  ```
  https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
  ```
- Open **Tools → Board → Boards Manager**
- Search for `esp32` and install **esp32 by Espressif Systems**


### Configure Board and Upload Settings

- **Tools → Board** → select `ESP32S3 Dev Module`
- **Tools → Port** → select the port for the connected board (e.g. `/dev/ttyACM0`)
- **Tools → USB CDC on Boot** → `Enabled`
- **Tools → USB Mode** → `Hardware CDC and JTAG`


### Install Required Libraries

- Open **Tools → Manage Libraries**
- When prompted, always choose to install all dependencies
- Install the following libraries:
  - `TFT_eSPI` by Bodmer
  - `HX711 Arduino Library` by Bogdan Necuda, Andreas Motl
  - `DHT sensor library` by Adafruit
  - `Adafruit BME280 Library` by Adafruit
  - `Adafruit Unified Sensor` by Adafruit
  - `OneWire` by Paul Stoffregen
  - `DallasTemperature` by Miles Burton
  - `PubSubClient` by Nick O'Leary

### Configure TFT_eSPI for LilyGO T-Display-S3

- Locate the library folder, typically `~/Arduino/libraries/TFT_eSPI/`
- Open `User_Setup_Select.h` in a text editor
- Comment out the default line:
  ```cpp
  // #include <User_Setup.h>
  ```
- Uncomment the line for the T-Display-S3:
  ```cpp
  #include <User_Setups/Setup206_LilyGo_T_Display_S3.h>
  ```
- Save the file — without this step the display will not work

### Configure Credentials

- Copy `config.h.example` to `config.h`:
  ```bash
  cp config.h.example config.h
  ```
- Open `config.h` and fill in your WiFi SSID, password, and MQTT broker details

### Flash the Sketch

- Open `beehive.ino` in Arduino IDE
- Click **Upload** (→)
- If the upload fails, close the Serial Monitor and Serial Plotter and try again

---

## Camera Node (Raspberry Pi 5)

### Prerequisites

- Raspberry Pi 5 running Raspberry Pi OS (64-bit)
- Raspberry Pi Camera 3 connected via CSI ribbon cable
- Python 3.13.5 (pre-installed on Raspberry Pi OS)

### Install Tailscale (VPN)

- Install Tailscale:
  ```bash
  curl -fsSL https://tailscale.com/install.sh | sh
  ```
- Connect to your Tailscale network:
  ```bash
  sudo tailscale up
  ```

### Create a Virtual Environment

- The virtual environment must be created with access to system-wide packages
  so that `picamera2` and `libcamera`, which are pre-installed on Raspberry Pi OS,
  are available without reinstalling them:
  ```bash
  python3 -m venv --system-site-packages ~/Desktop/beehive/.venv
  ```
- Activate the virtual environment:
  ```bash
  source ~/Desktop/beehive/.venv/bin/activate
  ```

### Install Python Dependencies

- Install the required packages into the virtual environment:
  ```bash
  pip install -r requirements.txt
  ```
  The `requirements.txt` file is included in the repository and contains:
  - `ultralytics` — YOLO model inference and ByteTrack multi-object tracking
  - `paho-mqtt` — MQTT client
  - `opencv-python` — video capture and frame processing
### Set Up the YOLO Model

- Copy the model folder from the repository to the expected location:
  ```bash
  cp -r src/models/mybeesyolo11.ncnn ~/Desktop/
  ```
  The model must be located at `~/Desktop/mybeesyolo11.ncnn/best_ncnn_model`
  to match the `MODEL_PATH` defined in `bee_counter.py`.
### Configure Credentials

- Copy `config.py.example` to `config.py`:
  ```bash
  cp config.py.example config.py
  ```
- Open `config.py` and fill in your MQTT broker IP address and other details




