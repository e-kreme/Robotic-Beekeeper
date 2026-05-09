# User Manual

## Sensor Node (ESP32-S3)

### Overview

- Once flashed and wired according to the `schematic.png`, the device runs fully autonomously
- No regular interaction is required

### Monitoring

- **Display** — the built-in TFT display shows current weight, outdoor temperature, indoor temperature/humidity/pressure, and WiFi/MQTT connection status
- **Grafana** — sensor readings are published to the MQTT broker every 5 minutes and can be viewed in the Grafana dashboard

### Taring the Scale *(one-time, only if needed)*

- Remove any weight from the scale
- Connect to the board via Serial Monitor at baud rate `115200`
- Send `t` / `T` — the zero offset is recalculated and stored automatically

### Calibrating the Scale *(one-time, only if needed)*

- The default calibration values in the sketch were obtained during initial setup and should work without any changes
- If recalibration is needed:
  - Set `KNOWN_MASS` in `beehive.ino` to the exact mass of your reference weight in kilograms
  - Place the reference weight on the scale
  - Connect via Serial Monitor at baud rate `115200` and send `c` / `C`

### Troubleshooting

- **Display shows `BME280 ERROR`** — check the I2C wiring (SDA, SCL, VCC, GND)
- **Display shows `DS18B20 error`** — check the 1-Wire wiring and the pull-up resistor
- **WiFi/MQTT indicators red** — check network credentials in `config.h` and verify the broker is reachable
- **Upload fails** — close the Serial Monitor and Serial Plotter and try again

---

## Camera Node (Raspberry Pi 5)

### Overview

- Once set up, the bee counter runs manually by activating the virtual environment and launching the script
- Counts are published to the MQTT broker every 5 minutes and logged locally to a CSV file

### Running the Bee Counter

- Activate the virtual environment:
  ```bash
  source ~/Desktop/beehive/.venv/bin/activate
  ```
- Run the script:
  ```bash
  python3 ~/Desktop/beehive/bee_counter.py
  ```
- Stop it at any time with `Ctrl+C` — a final MQTT publish is sent automatically before the script exits

### Monitoring

- **Grafana** — bee traffic counts (bees in, bees out, pollen carriers) are published to the MQTT broker and can be viewed in the Grafana dashboard
- **CSV log** — every crossing event is logged locally to `~/Desktop/beehive/bee_count_log.csv` as a backup

### Debug Output

- While running, the script prints a status line every 5 seconds:
  ```
  [DEBUG] FPS: 14.3 | tracked: 4 | CPU temp: 61.2 °C
  ```
- On exit, a CPU temperature summary is printed:
  ```
  [DEBUG] Temperature — min: 58.1 °C  avg: 62.4 °C  max: 71.3 °C
  ```

### Troubleshooting

- **`MQTT connection failed at startup`** — check the broker IP in `config.py` and verify the broker is reachable; counting and CSV logging will continue regardless
- **Low FPS in debug output** — YOLO inference is CPU-bound; ensure no other heavy processes are running on the Raspberry Pi
- **Model not found error** — verify the model is located at `~/Desktop/mybeesyolo11.ncnn/best_ncnn_model`
- **Camera not detected** — verify the CSI ribbon cable is properly seated and the camera is enabled in `raspi-config`











