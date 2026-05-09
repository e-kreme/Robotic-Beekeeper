/**
 * @file beehive.ino
 * @brief Sensor node firmware for the beehive monitoring system.
 *
 * Reads weight (HX711 + YZC-1B load cell), outdoor temperature (DS18B20),
 * and indoor temperature, humidity, and pressure (BME280). Sensor readings
 * are displayed on the built-in TFT display and published to an MQTT broker
 * over WiFi as a JSON payload every 5 minutes.
 *
 * @details
 * Part of the bachelor's thesis at VUT FIT 2025/2026: Robotic Beekeeper.
 * The thesis deals with the design and implementation of an automated beehive monitoring system.
 *
 * @author Eliška Křeménková (xkremee00)
 * @date 20. 12. 2025
 */

#include "TFT_eSPI.h"
#include "HX711.h"
#include "OneWire.h"
#include "DallasTemperature.h"
#include "Wire.h"
#include "Adafruit_Sensor.h"
#include "Adafruit_BME280.h"
#include "WiFi.h"
#include "PubSubClient.h"
#include "config.h"

// ---------------------------------------------------------------------------
// Pin definitions
// ---------------------------------------------------------------------------

/** @brief HX711 data pin. */
static constexpr int HX_DT = 10;

/** @brief HX711 clock pin. */
static constexpr int HX_SCK = 18;

/** @brief DS18B20 1-Wire data pin. */
static constexpr int DS18B20_PIN = 11;

/** @brief I2C SDA pin for BME280. */
static constexpr int SDA_PIN = 43;

/** @brief I2C SCL pin for BME280. */
static constexpr int SCL_PIN = 44;

// ---------------------------------------------------------------------------
// Timing
// ---------------------------------------------------------------------------

/** @brief Interval between sensor reads and display updates (milliseconds). */
static constexpr unsigned long DISPLAY_INTERVAL = 2000;

/** @brief Interval between MQTT publishes (milliseconds). */
static constexpr unsigned long MQTT_INTERVAL = 5 * 60000;

// ---------------------------------------------------------------------------
// Weight filtering
// ---------------------------------------------------------------------------

/** @brief Exponential moving average (EMA) smoothing factor for weight. */
static constexpr float EMA_ALPHA = 0.2f;

// ---------------------------------------------------------------------------
// Global objects
// ---------------------------------------------------------------------------

TFT_eSPI tft;                           ///< TFT display
HX711 scale;                            ///< Load cell ADC
OneWire one_wire(DS18B20_PIN);          ///< 1-wire bus
DallasTemperature ds18b20(&one_wire);   ///< DS18B20 sensor
Adafruit_BME280 bme;                    ///< BME280 sensor
WiFiClient wifi_client;                 ///< TCP client used by MQTT
PubSubClient mqtt(wifi_client);         ///< MQTT client

// ---------------------------------------------------------------------------
// Scale calibration state
// ---------------------------------------------------------------------------

/** @brief Raw ADC reading with no load on the scale (tare offset). */
static long offset_raw = -213254;

/** @brief ADC counts per kilogram (calibration factor). */
float counts_per_kg = -39335.31f;

/** @brief Known reference mass used during calibration (kg). */
const float KNOWN_MASS = 56.5f;

// ---------------------------------------------------------------------------
// Weight filter state
// ---------------------------------------------------------------------------

float kg_filtered = 0.0f;               ///< Current EMA-filtered weight value
bool kg_filter_init = false;            ///< True after the EMA has been seeded

// ---------------------------------------------------------------------------
// Timing state
// ---------------------------------------------------------------------------

unsigned long last_display = 0;         ///< Timestamp of the last display update (ms)
unsigned long last_mqtt = 0;            ///< Timestamp of the last MQTT publish (ms)

// ---------------------------------------------------------------------------
// Scale calibration
// ---------------------------------------------------------------------------

/**
 * @brief Tares the scale by averaging 20 raw readings as the zero offset.
 *
 * Call with no load on the scale. The result is stored in offset_raw.
 * Trigger via the 't' serial command.
 */
void tare_scale() {
  Serial.println("Taring...");
  offset_raw = scale.read_average(20);
  Serial.print("Tare offset = ");
  Serial.println(offset_raw);
}

/**
 * @brief Calibrates the scale using a known reference mass.
 *
 * Call with known_kg placed on the scale. Computes and stores the
 * ADC counts-per-kilogram factor in counts_per_kg.
 * Trigger via the 'c' serial command.
 *
 * @param known_kg  Mass of the reference weight placed on the scale (kg).
 */
void calibrate_scale(float known_kg) {
  long raw = scale.read_average(20);
  counts_per_kg = (float)(raw - offset_raw) / known_kg;
  Serial.print("Cal counts_per_kg = ");
  Serial.println(counts_per_kg, 2);
}

// ---------------------------------------------------------------------------
// Weight reading
// ---------------------------------------------------------------------------

/**
 * @brief Reads and returns the current hive weight with EMA filtering.
 *
 * @param[out] kg_out  Filtered weight in kilograms.
 * @return             true if a valid reading was obtained,
 *                     false if the ADC is not ready or the scale is uncalibrated.
 */
bool read_weight(float &kg_out) {
  if (!scale.is_ready() || counts_per_kg == 0) {
    return false;
  }

  // Average 5 raw ADC readings and convert to kilograms
  float kg = (float)(scale.read_average(5) - offset_raw) / counts_per_kg;

  if (!kg_filter_init) {
    kg_filtered = kg;
    kg_filter_init = true;
  } else {
    kg_filtered = EMA_ALPHA * kg + (1.0f - EMA_ALPHA) * kg_filtered;
  }

  kg_out = kg_filtered;
  return true;
}

// ---------------------------------------------------------------------------
// WiFi
// ---------------------------------------------------------------------------

/**
 * @brief Attempts to connect to the WiFi network defined in config.h.
 *
 * Tries for up to 10 seconds (20 attempts × 500 ms). If the connection
 * cannot be established within that window, the function returns and the
 * sketch continues -- the connection will be retried by wifi_check().
 */
void wifi_connect() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(" connected! IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(" failed, will retry in background.");
  }
}

/**
 * @brief Checks the WiFi connection and reconnects if it has been lost.
 */
void wifi_check() {
  if (WiFi.status() != WL_CONNECTED) {
    if (WiFi.status() != WL_DISCONNECTED) {
      WiFi.disconnect();
      delay(1000);
    }
    Serial.println("WiFi lost, reconnecting...");
    wifi_connect();
  }
}

// ---------------------------------------------------------------------------
// MQTT
// ---------------------------------------------------------------------------

/**
 * @brief Attempts to connect to the MQTT broker defined in config.h.
 *
 * Does nothing if WiFi is not connected. Tries up to 5 times with a 1-second
 * delay between attempts. If all attempts fail, the function returns and the
 * connection will be retried by mqtt_check().
 */
void mqtt_connect() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  Serial.print("Connecting to MQTT broker");
  int attempts = 0;
  while (!mqtt.connected() && attempts < 5) {
    if (mqtt.connect(MQTT_ID)) {
      Serial.println(" connected!");
    } else {
      Serial.print(".");
      delay(1000);
      attempts++;
    }
  }
  if (!mqtt.connected()) {
    Serial.println(" failed, will retry later.");
  }
}

/**
 * @brief Checks the MQTT connection and reconnects if it has been lost.
 */
void mqtt_check() {
  if (!mqtt.connected()) {
    mqtt_connect();
  }
}

/**
 * @brief Publishes a sensor reading to the MQTT broker as a JSON payload.
 *
 * Published topic is defined by MQTT_TOPIC in config.h.
 *
 * Payload format:
 * {"weight":<kg>,"t_o":<°C>,"t":<°C>,"h":<%>,"p":<hPa>}
 *
 * @param m    Filtered hive weight (kg).
 * @param t_o  Outdoor temperature from DS18B20 (°C).
 * @param t_i  Indoor temperature from BME280 (°C).
 * @param h_i  Indoor relative humidity from BME280 (%).
 * @param p_i  Indoor atmospheric pressure from BME280 (hPa).
 */
void mqtt_publish(float m, float t_o, float t_i, float h_i, float p_i) {
  if (!mqtt.connected()) {
    return;
  }

  char payload[128];
  snprintf(payload, sizeof(payload),
    "{\"weight\":%.4f,\"t_o\":%.1f,\"t\":%.1f,\"h\":%.0f,\"p\":%.1f}", m, t_o, t_i, h_i, p_i);

  if (mqtt.publish(MQTT_TOPIC, payload)) {
    Serial.print("MQTT sent: ");
    Serial.println(payload);
  } else {
    Serial.println("MQTT publish failed.");
  }
}

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

/**
 * @brief Updates the TFT display with the latest sensor readings.
 *
 * The top-right corner shows WiFi and MQTT connection status in green
 * (connected) or red (disconnected). The main area shows weight, outdoor
 * temperature, and indoor temperature/humidity/pressure. Sensor error
 * strings are shown in place of values when a reading is invalid.
 *
 * @param m      Filtered hive weight (kg).
 * @param ok_m   true if the weight reading is valid.
 * @param t_o    Outdoor temperature (°C).
 * @param ok_ds  true if the DS18B20 reading is valid.
 * @param t_i    Indoor temperature (°C).
 * @param h_i    Indoor relative humidity (%).
 * @param p_i    Indoor atmospheric pressure (hPa).
 * @param ok_bme true if the BME280 reading is valid.
 */
void update_display(float m, bool ok_m, float t_o, bool ok_ds, float t_i, float h_i, float p_i, bool ok_bme) {
  tft.fillRect(140, 0, 100, 20, TFT_BLACK);
  tft.setCursor(180, 10);
  tft.setTextColor(WiFi.status() == WL_CONNECTED ? TFT_GREEN : TFT_RED, TFT_BLACK);
  tft.print("WiFi ");
  tft.setTextColor(mqtt.connected() ? TFT_GREEN : TFT_RED, TFT_BLACK);
  tft.print("MQTT");
  tft.setTextColor(TFT_GREEN, TFT_BLACK);

  tft.fillRect(0, 70, 240, 90, TFT_BLACK);
  tft.setCursor(10, 70);
  if (ok_m) {
    tft.printf("m: %.2f kg", m);
  } else {
    tft.println("m: --");
  }

  tft.setCursor(10, 100);
  if (ok_ds) {
    tft.printf("out: t: %.1f C", t_o);
  } else {
    tft.println("DS18B20 error");
  }

  tft.setCursor(10, 130);
  if (ok_bme) {
    tft.printf("in: t: %.1f C h: %.1f %% p: %.1f hPa", t_i, h_i, p_i);
  } else {
    tft.println("BME error");
  }
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

/**
 * @brief Initialises all peripherals and establishes network connections.
 *
 * Execution order: display → load cell → DS18B20 → BME280 → WiFi → MQTT.
 * The display shows "Sensors OK" or "BME280 ERROR" depending on whether the
 * BME280 is detected. Serial commands available after setup:
 *   - t / T  Tare the scale (no load must be present).
 *   - c / C  Calibrate the scale (KNOWN_MASS must be on the scale).
 */
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Display
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);
  tft.setTextSize(2);
  tft.setTextColor(TFT_GREEN, TFT_BLACK);
  tft.setCursor(10, 10);
  tft.println("Beehive node");

  // Load cell
  scale.begin(HX_DT, HX_SCK);

  // DS18B20
  ds18b20.begin();
  Serial.print("DS18B20 sensors found: ");
  Serial.println(ds18b20.getDeviceCount());

  // BME280
  Wire.begin(SDA_PIN, SCL_PIN);
  bool bme_ok = bme.begin(0x76);
  if (!bme_ok) bme_ok = bme.begin(0x77);

  tft.setCursor(10, 40);
  if (!bme_ok) {
    Serial.println("BME280 not found! Check wiring.");
    tft.setTextColor(TFT_RED, TFT_BLACK);
    tft.println("BME280 ERROR");
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
  } else {
    tft.println("Sensors OK");
  }

  // WiFi
  wifi_connect();

  // MQTT
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt_connect();

  Serial.println("Commands: 't' = tare, 'c' = calibrate");
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

/**
 * @brief Main loop -- runs continuously after setup().
 *
 * Every iteration: checks WiFi and MQTT connections and processes the
 * PubSubClient keep-alive. Every DISPLAY_INTERVAL milliseconds: reads all
 * sensors, updates the display, and logs readings to Serial. Every
 * MQTT_INTERVAL milliseconds: publishes a JSON payload to the MQTT broker
 * if both weight and outdoor temperature readings are valid.
 */
void loop() {
  // Handle one-time commands (tare/calibration)
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 't' || c == 'T') {
      tare_scale();
    } else if (c == 'c' || c == 'C') {
      calibrate_scale(KNOWN_MASS);
    }
  }

  // Check connections
  wifi_check();
  mqtt_check();
  mqtt.loop();  // Required by PubSubClient to maintain connection

  unsigned long now = millis();

  // Read sensors every 2s for display
  if (now - last_display >= DISPLAY_INTERVAL) {
    last_display = now;

    float m = 0;
    bool ok_m = read_weight(m);

    ds18b20.requestTemperatures();
    float t_o = ds18b20.getTempCByIndex(0);
    bool ok_ds = (t_o != DEVICE_DISCONNECTED_C && t_o != 85.0f);

    float t_i = bme.readTemperature();
    float h_i = bme.readHumidity();
    float p_i = bme.readPressure() / 100.0f;
    bool ok_bme = !isnan(t_i) && !isnan(h_i) && !isnan(p_i);

    if (!ok_ds) Serial.println("DS18B20 read failed");
    if (!ok_bme) Serial.println("BME280 read failed");
    if (!ok_m) Serial.println("Weight not ready/calibrated");

    update_display(m, ok_m, t_o, ok_ds, t_i, h_i, p_i, ok_bme);

    // MQTT publish every 5 minutes
    if (now - last_mqtt >= MQTT_INTERVAL) {
      last_mqtt = now;
      if (ok_m && ok_ds) {
        mqtt_publish(m, t_o, t_i, h_i, p_i);
      }
    }
  }
}

