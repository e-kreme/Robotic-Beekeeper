"""
subscriber.py
---------
MQTT subscriber and database writer for the beehive monitoring system.

Connects to the local MQTT broker, subscribes to sensor and camera topics,
and persists incoming readings to a SQLite database. Runs continuously as
the central data collection process on the Raspberry Pi 4 server.

Part of the bachelor's thesis at VUT FIT 2025/2026: Robotic Beekeeper.
The thesis deals with the design and implementation of an automated beehive monitoring system.

Author:     Eliška Křeménková (xkremee00)
Date:       20. 12. 2025
"""

import sqlite3
import json
from datetime import datetime
import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MQTT_HOST = "localhost"                         # broker runs on the same machine
MQTT_PORT = 1883                                # standard unencrypted MQTT port
MQTT_TOPIC_SENSORS = "beehive/hive1/sensors"
MQTT_TOPIC_CAMERA  = "beehive/hive1/camera"
DB_PATH = "/var/lib/beehive/beehive_v2.db"

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def init_db():
    con = sqlite3.connect(DB_PATH)

    con.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            weight_kg   REAL,
            t_o         REAL,
            t           REAL,
            h           REAL,
            p           REAL
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS camera_readings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            bees_in     INTEGER,
            bees_out    INTEGER,
            pollen_in   INTEGER
        )
    """)

    con.commit()
    con.close()

def save_sensor_reading(timestamp, weight, t_o, t, h, p):
    """Insert a single sensor reading into the readings table."""
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO readings (timestamp, weight_kg, t_o, t, h, p) VALUES (?, ?, ?, ?, ?, ?)",
        (timestamp, weight, t_o, t, h, p)
    )
    con.commit()
    con.close()

def save_camera_reading(timestamp, bees_in, bees_out, pollen_in):
    """Insert a single camera reading into the camera_readings table."""
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO camera_readings (timestamp, bees_in, bees_out, pollen_in) VALUES (?, ?, ?, ?)",
        (timestamp, bees_in, bees_out, pollen_in)
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------

def on_connect(client, userdata, connect_flags, reason_code, properties=None):
    """Called when the client connects to the broker.

    Subscribes to both sensor and camera topics on successful connection.
    """
    if reason_code == 0:
        print("Connected to broker.")
        client.subscribe(MQTT_TOPIC_SENSORS)
        print(f"Subscribed to {MQTT_TOPIC_SENSORS}")
        client.subscribe(MQTT_TOPIC_CAMERA)
        print(f"Subscribed to {MQTT_TOPIC_CAMERA}")
    else:
        print(f"Connection failed, code {reason_code}")

def on_message(client, userdata, message):
    """Called when a message is received on a subscribed topic.

    Parses the JSON payload, saves the reading to the database,
    and logs it to the system journal via stdout. Handles sensor
    and camera topics separately.
    """
    try:
        data = json.loads(message.payload.decode())
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if message.topic == MQTT_TOPIC_SENSORS:
            weight = data.get("weight")
            t_o    = data.get("t_o")
            t      = data.get("t")
            h      = data.get("h")
            p      = data.get("p")

            save_sensor_reading(timestamp, weight, t_o, t, h, p)
            print(
                f"[{timestamp}] [sensors] "
                f"weight={weight} kg | "
                f"t_o={t_o} °C | "
                f"t={t} °C | "
                f"h={h} % | "
                f"p={p} hPa"
            )

        elif message.topic == MQTT_TOPIC_CAMERA:
            bees_in   = data.get("bees_in")
            bees_out  = data.get("bees_out")
            pollen_in = data.get("pollen_in")

            save_camera_reading(timestamp, bees_in, bees_out, pollen_in)
            print(
                f"[{timestamp}] [camera]  "
                f"bees_in={bees_in} | "
                f"bees_out={bees_out} | "
                f"pollen_in={pollen_in}"
            )

        else:
            print(f"[{timestamp}] Received message on unexpected topic: {message.topic}")

    except Exception as e:
        print(f"Error processing message: {e}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

init_db()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_HOST, MQTT_PORT)
client.loop_forever()
