"""
forecast_anomaly_detection.py
---------
Hourly prediction and anomaly detection for the beehive monitoring system.

Loads two pre-trained LightGBM models to predict the hourly weight delta and
indoor temperature of the hive. Compares predictions against actual sensor
readings, computes residuals, and flags anomalies when the residual exceeds
a configurable standard deviation threshold. Results are stored in the
SQLite database and anomalies are printed to the log file.

Intended to be run every hour via cron:
    0 * * * * /home/pi/beehive/venv/bin/python3 /home/pi/beehive/forecast_anomaly_detection.py >> /home/pi/beehive/anomalies.log 2>&1

Part of the bachelor's thesis at VUT FIT 2025/2026: Robotic Beekeeper.
The thesis deals with the design and implementation of an automated beehive monitoring system.

Author:     Eliška Křeménková (xkremee00)
Date:       2. 4. 2026
"""

import sqlite3
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = '/var/lib/beehive/beehive_v2.db'
MODEL_WEIGHT = '/home/pi/beehive/models/lgb_separate_weight-delta-noOutlier.txt'
MODEL_TEMP = '/home/pi/beehive/models/lgb_separate_t-i-3.txt'
FEAT_COLS = '/home/pi/beehive/models/lgb_feature_cols.json'

# number of standard deviations from the historical residual mean required to flag a reading as anomalous
ANOMALY_STD = 5.0

# ---------------------------------------------------------------------------
# Load models
# ---------------------------------------------------------------------------

model_w = lgb.Booster(model_file=MODEL_WEIGHT)
model_t = lgb.Booster(model_file=MODEL_TEMP)
with open(FEAT_COLS) as f:
    feature_cols = json.load(f)

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

con = sqlite3.connect(DB_PATH, timeout=30)
con.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp            TEXT NOT NULL UNIQUE,
        pred_weight_delta    REAL,
        pred_t_i_3           REAL,
        actual_weight_delta  REAL,
        actual_t_i_3         REAL,
        resid_weight_delta   REAL,
        resid_t_i_3          REAL,
        anomaly_weight       INTEGER DEFAULT 0,
        anomaly_temp         INTEGER DEFAULT 0
    )
""")
con.commit()
con.close()

# ---------------------------------------------------------------------------
# Query sensor data
# ---------------------------------------------------------------------------

# fetch 172 hours (one week + buffer) to account for potential data gaps
since = (datetime.now() - timedelta(hours=400)).strftime('%Y-%m-%d %H:%M:%S')
con = sqlite3.connect(DB_PATH, timeout=30)
df = pd.read_sql_query(
    'SELECT timestamp, weight_kg, t_o, t, h, p FROM readings WHERE timestamp >= ? ORDER BY timestamp',
    con, params=(since,), parse_dates=['timestamp'], index_col='timestamp'
)
con.close()

# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

# rename columns to match model training conventions
df = df.rename(columns={'t': 't_i_3', 'weight_kg': 'weight_kg_noOutlier'})

# compute hourly weight delta and resample all columns to 1-hour intervals
df['weight_delta_noOutlier'] = df['weight_kg_noOutlier'].diff()
df = df.resample('1h').agg({
    'weight_kg_noOutlier' : 'last',
    'weight_delta_noOutlier' : 'sum',
    't_o' : 'mean',
    't_i_3' : 'mean',
    'h' : 'mean',
    'p' : 'mean',
})

# lag features -- past values at fixed hourly offsets
LAG_COLS = ['weight_delta_noOutlier', 't_o', 'h', 't_i_3', 'p']
LAGS = [1, 2, 3, 6, 12, 24, 48, 168]
for col in LAG_COLS:
    for lag in LAGS:
        df[f'{col}_lag{lag}'] = df[col].shift(lag)

# datetime features -- cyclical encodings to capture periodicity
df['hour'] = df.index.hour
df['dayofweek'] = df.index.dayofweek
df['month'] = df.index.month
df['hour_sin'] = np.sin(2 * np.pi * df.index.hour / 24)
df['hour_cos'] = np.cos(2 * np.pi * df.index.hour / 24)
df['day_sin'] = np.sin(2 * np.pi * df.index.dayofyear / 365)
df['day_cos'] = np.cos(2 * np.pi * df.index.dayofyear / 365)

# rolling statistics -- 24-hour and 168-hour (one week) windows
for col in LAG_COLS:
    df[f'{col}_roll24_mean'] = df[col].shift(1).rolling(24).mean()
    df[f'{col}_roll24_std'] = df[col].shift(1).rolling(24).std()
    df[f'{col}_roll168_mean'] = df[col].shift(1).rolling(168).mean()
    df[f'{col}_roll168_std'] = df[col].shift(1).rolling(168).std()

# drop rows with incomplete features (requires at least 168 hours of history)
df = df.dropna(subset=feature_cols)
if len(df) == 0:
    print('Not enough data to build features yet - need at least 168 hours of history')
    exit()

latest = df.iloc[[-1]]
X = latest[feature_cols]

# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------

pred_w = float(model_w.predict(X)[0])
pred_t = float(model_t.predict(X)[0])

actual_w = float(latest['weight_delta_noOutlier'].iloc[0])
actual_t = float(latest['t_i_3'].iloc[0])

resid_w = actual_w - pred_w
resid_t = actual_t - pred_t

# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

# compute residuals over the full history window (excluding the latest point)
resid_w_hist = (df['weight_delta_noOutlier'] - model_w.predict(df[feature_cols])).iloc[:-1]
resid_t_hist = (df['t_i_3'] - model_t.predict(df[feature_cols])).iloc[:-1]

# flag as anomaly if residual exceeds ANOMALY_STD standard deviations from
# the historical mean; weight anomaly also requires a minimum absolute change
anom_w = bool(
    abs(resid_w - resid_w_hist.mean()) > ANOMALY_STD * resid_w_hist.std()
    and abs(resid_w) > 0.5   # minimum meaningful weight change
)
anom_t = abs(resid_t - resid_t_hist.mean()) > ANOMALY_STD * resid_t_hist.std()

# ---------------------------------------------------------------------------
# Save results and print
# ---------------------------------------------------------------------------

ts = latest.index[0].strftime('%Y-%m-%d %H:%M:%S')

con = sqlite3.connect(DB_PATH, timeout=30)
con.execute("""
    INSERT OR REPLACE INTO predictions
        (timestamp, pred_weight_delta, pred_t_i_3,
         actual_weight_delta, actual_t_i_3,
         resid_weight_delta, resid_t_i_3,
         anomaly_weight, anomaly_temp)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (ts, pred_w, pred_t, actual_w, actual_t, resid_w, resid_t, int(anom_w), int(anom_t)))
con.commit()
con.close()

print(f'[{ts}]')
print(f'  weight_delta — predicted: {pred_w:.6f} kg/h | actual: {actual_w:.6f} kg/h | residual: {resid_w:.6f}')
print(f'  t_i_3        — predicted: {pred_t:.2f} °C   | actual: {actual_t:.2f} °C   | residual: {resid_t:.2f}')

if anom_w:
    print(f'  *** ANOMALY — weight_delta residual exceeds {ANOMALY_STD}σ threshold ***')
if anom_t:
    print(f'  *** ANOMALY — t_i_3 residual exceeds {ANOMALY_STD}σ threshold ***')
if not anom_w and not anom_t:
    print('  No anomalies detected')



