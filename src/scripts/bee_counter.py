"""
bee_counter.py
---------
Real-time bee traffic counter for the beehive monitoring system.

Captures video from the Raspberry Pi Camera 3, runs a YOLO object detection
model with ByteTrack multi-object tracking, and counts bees crossing a
horizontal line at the hive entrance. Distinguishes between bees entering
and leaving, and tracks pollen-carrying bees separately. Aggregated counts
are published to an MQTT broker every PUBLISH_INTERVAL_MIN minutes and logged
to a CSV file for local backup.

Part of the bachelor's thesis at VUT FIT 2025/2026: Robotic Beekeeper.
The thesis deals with the design and implementation of an automated beehive monitoring system.

Author:     Eliška Křeménková (xkremee00)
Date:       8. 4. 2026
"""

from picamera2 import Picamera2
from datetime import datetime
from pathlib import Path
from libcamera import controls
from ultralytics import YOLO
import cv2
import csv
import time
import json
import paho.mqtt.client as mqtt

from config import (MQTT_HOST, MQTT_PORT, MQTT_ID, MQTT_TOPIC, PUBLISH_INTERVAL_MIN)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

LENS_POSITION = 5.0         # manual focus position: 1 / distance in metres (5.0 ≈ 20 cm)
TARGET_FPS = 15             # target capture and inference rate
CROP = (0, 0, 2304, 1296)   # region of interest (left, top, right, bottom) in pixels
LINE_FRACTION = 1 / 2       # vertical position of the counting line as a fraction of frame height
CONFIDENCE = 0.4            # minimum YOLO detection confidence threshold

MODEL_PATH = Path.home() / "Desktop" / "mybeesyolo11.ncnn" / "best_ncnn_model"
LOG_FILE = Path.home() / "Desktop" / "bee_count_log.csv"

# YOLO class index to name mapping (must match the trained model)
CLASS_NAMES = {
    0: "bee",
    1: "bee_pollen",
}

BEE_CLASSES = {"bee", "bee_pollen"}
POLLEN_CLASSES = {"bee_pollen"}

PUBLISH_INTERVAL_SEC = PUBLISH_INTERVAL_MIN * 60
DEBUG_INTERVAL_SEC = 5

# ---------------------------------------------------------------------------
# DERIVED CONSTANTS
# ---------------------------------------------------------------------------

crop_left, crop_top, crop_right, crop_bottom = CROP
crop_h = crop_bottom - crop_top

# Y coordinate of the horizontal counting line in cropped frame pixels
LINE_Y = int(crop_h * LINE_FRACTION)

# minimum time between captured frames to maintain TARGET_FPS
FRAME_INTERVAL = 1.0 / TARGET_FPS

# ---------------------------------------------------------------------------
# MQTT SETUP
# ---------------------------------------------------------------------------

mqtt_connected = False

def on_connect(client, userdata, connect_flags, reason_code, properties=None):
    """Called by the MQTT client when a connection attempt completes."""
    global mqtt_connected
    if reason_code == 0:
        mqtt_connected = True

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    """Called by the MQTT client when the connection is lost."""
    global mqtt_connected
    mqtt_connected = False

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_ID)
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

try:
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()
except Exception as e:
    # not fatal — script will keep counting and saving CSV even without broker
    print(f"MQTT connection failed at startup: {e}")

# ---------------------------------------------------------------------------
# LOAD MODEL
# ---------------------------------------------------------------------------

model = YOLO(str(MODEL_PATH), task="detect")

# ---------------------------------------------------------------------------
# TRACKING STATE
# ---------------------------------------------------------------------------

# per-track history: {track_id: {"y": float, "cls": str, "frames": int}}
track_history = {}

# IDs that have already been counted to avoid double-counting
counted_ids = set()

# interval counts -- accumulate between publishes, then reset after each publish
counts = {
    "bees_in": 0,
    "bees_out": 0,
    "pollen_in": 0,
}

# ---------------------------------------------------------------------------
# CSV LOG SETUP
# ---------------------------------------------------------------------------

write_header = not LOG_FILE.exists()
log = open(LOG_FILE, "a", newline="")
writer = csv.writer(log)
if write_header:
    writer.writerow([
        "timestamp",
        "event",
        "direction",
        "class",
        "bees_in_total",
        "bees_out_total",
        "pollen_in_total",
    ])
    log.flush()

# running totals for CSV (never resets)
totals = {"bees_in": 0, "bees_out": 0, "pollen_in": 0}

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def log_crossing(direction, cls_name):
    """Append a single crossing event to the CSV log."""
    writer.writerow([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "crossing",
        direction,
        cls_name,
        totals["bees_in"],
        totals["bees_out"],
        totals["pollen_in"],
    ])
    log.flush()

def publish_counts():
    """Publish aggregated counts for the last interval to MQTT, then reset them."""
    payload = json.dumps({
        "bees_in": counts["bees_in"],
        "bees_out": counts["bees_out"],
        "pollen_in": counts["pollen_in"],
    })

    if mqtt_connected:
        mqtt_client.publish(MQTT_TOPIC, payload, qos=0)

    # reset interval counts regardless of whether publish succeeded
    counts["bees_in"] = 0
    counts["bees_out"] = 0
    counts["pollen_in"] = 0

def read_cpu_temp():
    """Read the Raspberry Pi CPU temperature from the system thermal zone.

    Returns:
        float: CPU temperature in °C, or 0.0 if unavailable.
    """
    try:
        temp_str = Path("/sys/class/thermal/thermal_zone0/temp").read_text()
        return int(temp_str.strip()) / 1000.0
    except Exception:
        return 0.0

# ---------------------------------------------------------------------------
# CAMERA SETUP
# ---------------------------------------------------------------------------

# camera size matches the CROP region -- RGB888 required by OpenCV
camera = Picamera2()
config = camera.create_video_configuration(
    main={
        "size": (2304, 1296),
        "format": "RGB888",
    },
    controls={
        "AfMode": controls.AfModeEnum.Manual,
        "LensPosition": LENS_POSITION,
        "FrameRate": TARGET_FPS,
    }
)
camera.configure(config)
camera.start()
time.sleep(2) # allow the camera to stabilise before the first capture

# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------

last_frame_time = 0
last_publish_time = time.time()
last_debug_time = time.time()

# state for FPS calculation and temperature tracking
frame_count = 0
temp_samples = []

try:
    while True:
        now = time.time()

        # throttle to TARGET_FPS
        if now - last_frame_time < FRAME_INTERVAL:
            time.sleep(0.005)
            continue
        last_frame_time = now
        frame_count += 1

        # capture and crop frame, convert RGB to BGR for OpenCV/YOLO
        frame = camera.capture_array()
        frame = frame[crop_top:crop_bottom, crop_left:crop_right]
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # run YOLO detection with ByteTrack
        results = model.track(
            frame,
            conf = CONFIDENCE,
            persist = True,
            tracker = "bytetrack.yaml",
            verbose = False,
            imgsz = 640,
        )

        detections = results[0].boxes
        active_ids = set()

        if detections is not None and detections.id is not None:
            for box in detections:
                if box.id is None:
                    continue

                track_id = int(box.id.item())
                cls_id = int(box.cls.item())
                cls_name = CLASS_NAMES.get(cls_id, "")

                # only y-coordinate is needed for line crossing detection
                _, current_y, _, _ = box.xywh[0].tolist()

                active_ids.add(track_id)

                if cls_name not in BEE_CLASSES:
                    continue

                if track_id not in track_history:
                    # seed history on first appearance, skip crossing check
                    track_history[track_id] = {
                        "y": current_y,
                        "cls": cls_name,
                        "frames": 1,
                    }
                    continue

                prev_y = track_history[track_id]["y"]
                n_frames = track_history[track_id]["frames"]

                # require at least 3 frames of history before counting to avoid noisy detections
                if n_frames >= 3 and track_id not in counted_ids:
                    crossed_in = prev_y < LINE_Y <= current_y   # moving downward (into hive)
                    crossed_out = prev_y > LINE_Y >= current_y  # moving upward (out of hive)

                    if crossed_in:
                        counts["bees_in"] += 1
                        totals["bees_in"] += 1
                        counted_ids.add(track_id)

                        if cls_name in POLLEN_CLASSES:
                            counts["pollen_in"] += 1
                            totals["pollen_in"] += 1

                        log_crossing("in", cls_name)

                    elif crossed_out:
                        counts["bees_out"] += 1
                        totals["bees_out"] += 1
                        counted_ids.add(track_id)

                        log_crossing("out", cls_name)

                track_history[track_id] = {
                    "y": current_y,
                    "cls": cls_name,
                    "frames": n_frames + 1,
                }

        # clean up tracks that disappeared from the current frame
        for lost_id in set(track_history.keys()) - active_ids:
            del track_history[lost_id]

        # publish aggregated counts every PUBLISH_INTERVAL_SEC
        if now - last_publish_time >= PUBLISH_INTERVAL_SEC:
            publish_counts()
            last_publish_time = now

        # print debug info every DEBUG_INTERVAL_SEC
        if now - last_debug_time >= DEBUG_INTERVAL_SEC:
            elapsed = now - last_debug_time
            fps = frame_count / elapsed
            temp = read_cpu_temp()
            temp_samples.append(temp)

            print(
                f"[DEBUG] FPS: {fps:.1f} | "
                f"tracked: {len(active_ids)} | "
                f"CPU temp: {temp:.1f} °C"
            )

            frame_count = 0
            last_debug_time = now

except KeyboardInterrupt:
    # final publish of whatever has accumulated since the last interval
    publish_counts()
    camera.stop()
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    log.close()

    # print temperature summary if any samples were collected
    if temp_samples:
        print(
            f"[DEBUG] Temperature — "
            f"min: {min(temp_samples):.1f} °C "
            f"avg: {sum(temp_samples)/len(temp_samples):.1f} °C "
            f"max: {max(temp_samples):.1f} °C"
        )
