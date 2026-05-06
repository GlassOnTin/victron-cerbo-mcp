# Copy this file to config.py on the Pico and fill in your values.
# config.py is gitignored.

# --- WiFi ---
WIFI_SSID = "your-ssid"
WIFI_PASSWORD = "your-wifi-password"
WIFI_COUNTRY = "GB"               # ISO country code; needed to use channels 12/13

# --- MQTT broker (Cerbo's dbus-flashmq) ---
MQTT_HOST = "venus.local"        # or the Cerbo's static LAN IP
MQTT_PORT = 8883                  # 8883 = TLS (Settings > Services > MQTT on LAN (SSL))
MQTT_USE_TLS = True
MQTT_TLS_INSECURE = True          # Cerbo's cert is self-signed; verify=False on LAN
MQTT_USERNAME = "pico"            # Cerbo ignores the value; umqtt.simple needs truthy to send the flag
MQTT_PASSWORD = "your-cerbo-mqtt-password"
MQTT_CLIENT_ID = "sdm120-grid-meter"
MQTT_TOPIC = "victron/grid/sdm120"      # dbus-mqtt-grid subscribes here
MQTT_KEEPALIVE_S = 30
PUBLISH_PERIOD_S = 2.0            # one publish every N seconds

# --- SDM120CT-M Modbus RTU ---
# Defaults from the meter at factory: addr=1, 2400 8N1.
# Set up via the meter's setup button if you've changed any of these.
SDM_ADDR = 1
SDM_BAUD = 2400
SDM_PARITY = None                 # None / 0 (even) / 1 (odd)
SDM_STOP_BITS = 1

# --- Pico 2 W UART pins (UART0 by default) ---
UART_ID = 0
UART_TX_PIN = 0                   # GP0 -> MAX485 DI
UART_RX_PIN = 1                   # GP1 <- MAX485 RO
UART_DE_PIN = None                # None = auto-direction module (HW-519 etc). GPIO# for true MAX485 with DE+RE pins.

# --- Behaviour ---
MODBUS_TIMEOUT_MS = 500
MODBUS_RETRIES = 3
WATCHDOG_TIMEOUT_MS = 0           # 0 = disabled. Set to 8000 once running stable on hardware.
DEBUG = False                     # True = print every Modbus exchange

# --- Sign convention ---
# Set to -1 if the CT clamp ended up reversed and you don't want to swap leads.
# Victron expects: power > 0 = importing from grid, power < 0 = exporting.
POWER_SIGN = 1
