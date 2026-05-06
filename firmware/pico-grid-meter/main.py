"""SDM120 → MQTT bridge for Raspberry Pi Pico 2 W.

Reads the Eastron SDM120CT-M over RS485 (via MAX485 transceiver), formats
the result as JSON in the shape mr-manuel/dbus-mqtt-grid expects, and
publishes to the Cerbo's MQTT broker over TLS.

Layout:
  config.py        — credentials and pinout (copy from config.example.py)
  modbus_rtu.py    — minimal Modbus master with DE/RE control
  sdm120.py        — SDM120 register map and reader
  wifi_mgr.py      — WiFi connect/reconnect
  mqtt_client.py   — MQTT publisher with reconnect
  main.py          — this file: glue and main loop
"""

import json
import time

from machine import WDT

import config
from mqtt_client import MqttPublisher
from sdm120 import SDM120
from modbus_rtu import ModbusRTU
from wifi_mgr import WiFi


def _build_payload(reading: dict, sign: int) -> bytes:
    """Format readings into the JSON the dbus-mqtt-grid driver expects.

    Convention: power > 0 = importing from grid, power < 0 = exporting.
    """
    p = reading["power"] * sign
    i = reading["current"] * sign
    payload = {
        "grid": {
            "power": round(p, 2),
            "L1": {
                "power": round(p, 2),
                "voltage": round(reading["voltage"], 2),
                "current": round(i, 3),
                "frequency": round(reading["frequency"], 3),
            },
            "energy_forward": round(reading["energy_forward"], 3),
            "energy_reverse": round(reading["energy_reverse"], 3),
        }
    }
    return json.dumps(payload).encode("utf-8")


def _read_with_retry(meter: SDM120, retries: int):
    last = None
    for attempt in range(retries):
        try:
            return meter.read_all()
        except Exception as e:
            last = e
            if config.DEBUG:
                print("[modbus] attempt %d failed: %s" % (attempt + 1, e))
            time.sleep_ms(50)
    raise last


class _NoopWdt:
    def feed(self): pass


def main():
    print("[boot] sdm120 grid-meter bridge starting")

    if config.WATCHDOG_TIMEOUT_MS and config.WATCHDOG_TIMEOUT_MS > 0:
        wdt = WDT(timeout=config.WATCHDOG_TIMEOUT_MS)
        print("[boot] watchdog armed at %d ms" % config.WATCHDOG_TIMEOUT_MS)
    else:
        wdt = _NoopWdt()
        print("[boot] watchdog DISABLED (set WATCHDOG_TIMEOUT_MS > 0 to enable)")

    wifi = WiFi(
        config.WIFI_SSID,
        config.WIFI_PASSWORD,
        country=getattr(config, "WIFI_COUNTRY", "GB"),
        wdt=wdt,
    )
    while not wifi.connect():
        print("[wifi] connect failed, retrying")
        wdt.feed()
        time.sleep(2)
    print("[wifi] up:", wifi.ifconfig)

    bus = ModbusRTU(
        uart_id=config.UART_ID,
        tx_pin=config.UART_TX_PIN,
        rx_pin=config.UART_RX_PIN,
        de_pin=config.UART_DE_PIN,
        baud=config.SDM_BAUD,
        parity=config.SDM_PARITY,
        stop=config.SDM_STOP_BITS,
        timeout_ms=config.MODBUS_TIMEOUT_MS,
    )
    meter = SDM120(bus, addr=config.SDM_ADDR)

    mqtt = MqttPublisher(
        client_id=config.MQTT_CLIENT_ID,
        host=config.MQTT_HOST,
        port=config.MQTT_PORT,
        username=config.MQTT_USERNAME,
        password=config.MQTT_PASSWORD,
        use_tls=config.MQTT_USE_TLS,
        tls_insecure=config.MQTT_TLS_INSECURE,
        keepalive_s=config.MQTT_KEEPALIVE_S,
    )
    mqtt.connect()

    period_ms = int(config.PUBLISH_PERIOD_S * 1000)
    next_tick = time.ticks_ms()
    consecutive_failures = 0

    while True:
        wdt.feed()

        if not wifi.is_connected:
            print("[wifi] dropped, reconnecting")
            wifi.connect()

        try:
            reading = _read_with_retry(meter, config.MODBUS_RETRIES)
            payload = _build_payload(reading, config.POWER_SIGN)
            ok = mqtt.publish(config.MQTT_TOPIC, payload)
            if config.DEBUG:
                print("[publish %s]" % ("ok" if ok else "fail"), payload)
            consecutive_failures = 0 if ok else consecutive_failures + 1
        except Exception as e:
            consecutive_failures += 1
            print("[loop] error (%d in a row): %s" % (consecutive_failures, e))

        # Pace the loop. Skip catch-up if we ran long.
        next_tick = time.ticks_add(next_tick, period_ms)
        slack = time.ticks_diff(next_tick, time.ticks_ms())
        if slack > 0:
            time.sleep_ms(slack)
        else:
            next_tick = time.ticks_ms()


if __name__ == "__main__":
    main()
