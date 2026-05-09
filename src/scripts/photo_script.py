"""
photo_script.py
---------
Utility script for capturing cropped still images from the Raspberry Pi Camera 3
using a fixed manual focus position.

This script is not part of the deployed system -- it was used during
development and dataset collection for the bee detection model.

Part of the bachelor's thesis at VUT FIT 2025/2026: Robotic Beekeeper.
The thesis deals with the design and implementation of an automated beehive monitoring system.

Author:     Eliška Křeménková (xkremee00)
Date:       15. 3. 2025
"""

from picamera2 import Picamera2
from datetime import datetime
from pathlib import Path
from libcamera import controls
from PIL import Image
import time

INTERVAL = 5                # time between photos (seconds)
LENS_POSITION = 5.0         # manual focus position: 1 / distance in metres
CROP = (0, 0, 2304, 1296)   # (left, top, right, bottom) in pixels

OUTPUT_DIR = Path.home()/"Desktop"/"bee_photos"
OUTPUT_DIR.mkdir(exist_ok=True)

# Configure camera for still capture with manual focus
camera = Picamera2()
config = camera.create_still_configuration(
    main={"size": (2304, 1296)},
    controls={"AfMode": controls.AfModeEnum.Manual, "LensPosition": LENS_POSITION}
)
camera.configure(config)
camera.start()

print(f"Camera started, interval = {INTERVAL} s, lens position = {LENS_POSITION}")
time.sleep(2)   # allow the camera to stabilise before the first capture

try:
    while True:
        timestamp = datetime.now().strftime("bee_%Y%m%d_%H%M%S.jpg")
        filepath = OUTPUT_DIR/timestamp
        camera.capture_file(str(filepath))

        # crop the full-resolution frame and overwrite
        img = Image.open(filepath)
        img = img.crop(CROP)
        img.save(filepath)

        print(f"Saved: {filepath} (cropped to {img.size})")
        time.sleep(INTERVAL)

# Stop by pressing Ctrl + C
except KeyboardInterrupt:
    print("Stopped")
    camera.stop()