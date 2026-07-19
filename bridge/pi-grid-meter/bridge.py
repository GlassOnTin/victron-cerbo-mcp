"""SDM120 → Cerbo MQTT bridge (multi-meter).

Runs on a Pi attached to the house consumer unit. Reads one or more
Eastron SDM120CT-M meters every PUBLISH_PERIOD_S seconds via shared
USB-RS485 (Modbus RTU) and publishes one JSON document per meter to
the Cerbo's MQTT broker. The payload shape per meter depends on its
role: "grid" matches mr-manuel/dbus-mqtt-grid, "pv" matches
mr-manuel/dbus-mqtt-pv.

All credentials and tunables come from environment variables. Meters
are configured via METER_<N>_ADDR / METER_<N>_ROLE / METER_<N>_TOPIC
(see bridge.env.example).

Sign convention: power > 0 means
  - grid: importing from grid
  - pv:   producing
POWER_SIGN flips the meter's raw reading when the CT is wired the
"wrong way round" relative to the convention above.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import ssl
import struct
import sys
import time
from dataclasses import dataclass
from typing import Optional

import paho.mqtt.client as mqtt
import serial


log = logging.getLogger("grid-meter-bridge")


# --- SDM120CT-M input register map (Modbus FC 0x04) ---
# Each measurement is one big-endian IEEE-754 float in 2 consecutive registers.
REG_VOLTAGE = 0x0000          # V
REG_CURRENT = 0x0006          # A — sign reflects active power direction
REG_ACTIVE_POWER = 0x000C     # W — SIGNED (+ = imported, − = exported)
REG_FREQUENCY = 0x0046        # Hz
REG_IMPORT_ENERGY = 0x0048    # kWh, lifetime
REG_EXPORT_ENERGY = 0x004A    # kWh, lifetime


VALID_ROLES = ("grid", "pv")


@dataclass(frozen=True)
class MeterConfig:
    name: str
    slave_addr: int
    role: str
    topic: str
    power_sign: int


@dataclass(frozen=True)
class Config:
    serial_port: str
    serial_baud: int
    serial_parity: str
    serial_stopbits: int
    modbus_timeout_s: float
    modbus_retries: int

    mqtt_host: str
    mqtt_port: int
    mqtt_use_tls: bool
    mqtt_tls_insecure: bool
    mqtt_username: str
    mqtt_password: str
    mqtt_client_id: str
    mqtt_keepalive_s: int

    meters: tuple

    publish_period_s: float

    @classmethod
    def from_env(cls) -> "Config":
        def env_str(k, default=None, required=False):
            v = os.environ.get(k, default)
            if required and not v:
                raise SystemExit(f"missing required env var: {k}")
            return v

        def env_int(k, default):
            return int(os.environ.get(k, default))

        def env_float(k, default):
            return float(os.environ.get(k, default))

        def env_bool(k, default):
            v = os.environ.get(k, str(default)).strip().lower()
            return v in ("1", "true", "yes", "on")

        meters = []
        n = 1
        while True:
            addr_env = os.environ.get(f"METER_{n}_ADDR")
            if not addr_env:
                break
            role = os.environ.get(f"METER_{n}_ROLE", "").strip().lower()
            if role not in VALID_ROLES:
                raise SystemExit(
                    f"METER_{n}_ROLE must be one of {VALID_ROLES} (got {role!r})"
                )
            topic = os.environ.get(f"METER_{n}_TOPIC")
            if not topic:
                raise SystemExit(f"missing required env var: METER_{n}_TOPIC")
            meters.append(MeterConfig(
                name=os.environ.get(f"METER_{n}_NAME", f"meter{n}"),
                slave_addr=int(addr_env),
                role=role,
                topic=topic,
                power_sign=int(os.environ.get(f"METER_{n}_POWER_SIGN", "1")),
            ))
            n += 1
        if not meters:
            raise SystemExit("no meters configured: set METER_1_ADDR / METER_1_ROLE / METER_1_TOPIC")

        return cls(
            serial_port=env_str("SERIAL_PORT", "/dev/ttyUSB0"),
            serial_baud=env_int("SERIAL_BAUD", 9600),
            serial_parity=env_str("SERIAL_PARITY", "N"),
            serial_stopbits=env_int("SERIAL_STOPBITS", 1),
            modbus_timeout_s=env_float("MODBUS_TIMEOUT_S", 1.0),
            modbus_retries=env_int("MODBUS_RETRIES", 3),
            mqtt_host=env_str("MQTT_HOST", required=True),
            mqtt_port=env_int("MQTT_PORT", 8883),
            mqtt_use_tls=env_bool("MQTT_USE_TLS", True),
            mqtt_tls_insecure=env_bool("MQTT_TLS_INSECURE", True),
            mqtt_username=env_str("MQTT_USERNAME", "pi-bridge"),
            mqtt_password=env_str("MQTT_PASSWORD", required=True),
            mqtt_client_id=env_str("MQTT_CLIENT_ID", "sdm120-bridge"),
            mqtt_keepalive_s=env_int("MQTT_KEEPALIVE_S", 30),
            meters=tuple(meters),
            publish_period_s=env_float("PUBLISH_PERIOD_S", 2.0),
        )


# --- Modbus RTU master ---


def _crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class SDM120Bus:
    """One USB-RS485 port, shared by all meters on the chain."""

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._ser: Optional[serial.Serial] = None

    def _ensure_open(self):
        if self._ser is not None and self._ser.is_open:
            return
        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
        }
        self._ser = serial.Serial(
            port=self._cfg.serial_port,
            baudrate=self._cfg.serial_baud,
            parity=parity_map[self._cfg.serial_parity.upper()],
            stopbits=self._cfg.serial_stopbits,
            bytesize=8,
            timeout=self._cfg.modbus_timeout_s,
            write_timeout=self._cfg.modbus_timeout_s,
        )
        log.info("opened serial %s @ %d 8%s%d",
                 self._cfg.serial_port, self._cfg.serial_baud,
                 self._cfg.serial_parity, self._cfg.serial_stopbits)

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def _read_float(self, slave: int, reg: int) -> float:
        self._ensure_open()
        ser = self._ser
        req = bytes([slave, 0x04, (reg >> 8) & 0xFF, reg & 0xFF, 0, 2]) + _crc16(
            bytes([slave, 0x04, (reg >> 8) & 0xFF, reg & 0xFF, 0, 2])
        )

        last_exc: Optional[Exception] = None
        for attempt in range(self._cfg.modbus_retries):
            try:
                ser.reset_input_buffer()
                ser.write(req)
                ser.flush()
                deadline = time.monotonic() + self._cfg.modbus_timeout_s
                expected = 9
                buf = b""
                while len(buf) < expected and time.monotonic() < deadline:
                    chunk = ser.read(expected - len(buf))
                    if chunk:
                        buf += chunk
                    else:
                        break
                if len(buf) < 5:
                    raise OSError(f"short response ({len(buf)} bytes)")
                if buf[0] != slave or buf[1] != 0x04 or buf[2] != 4:
                    raise OSError(f"bad header: {buf[:3].hex()}")
                if _crc16(buf[:-2]) != buf[-2:]:
                    raise OSError(f"CRC mismatch: {buf.hex()}")
                return struct.unpack(">f", buf[3:7])[0]
            except Exception as e:
                last_exc = e
                if attempt < self._cfg.modbus_retries - 1:
                    time.sleep(0.05)
                if isinstance(e, serial.SerialException):
                    self.close()
        raise OSError(f"read slave={slave} reg=0x{reg:04X} failed after retries: {last_exc}")

    def read_all(self, slave: int) -> dict:
        return {
            "voltage": self._read_float(slave, REG_VOLTAGE),
            "current": self._read_float(slave, REG_CURRENT),
            "power": self._read_float(slave, REG_ACTIVE_POWER),
            "frequency": self._read_float(slave, REG_FREQUENCY),
            "energy_forward": self._read_float(slave, REG_IMPORT_ENERGY),
            "energy_reverse": self._read_float(slave, REG_EXPORT_ENERGY),
        }


# --- MQTT publisher ---


class MqttBridge:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cfg.mqtt_client_id,
        )
        self._client.username_pw_set(
            username=cfg.mqtt_username,
            password=cfg.mqtt_password,
        )
        if cfg.mqtt_use_tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            if cfg.mqtt_tls_insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self._client.tls_set_context(ctx)
        self._client.reconnect_delay_set(min_delay=2, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("mqtt connected: rc=%s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        log.warning("mqtt disconnected: rc=%s", reason_code)

    def start(self):
        log.info("connecting to mqtt %s:%d (tls=%s)",
                 self._cfg.mqtt_host, self._cfg.mqtt_port, self._cfg.mqtt_use_tls)
        self._client.connect_async(
            self._cfg.mqtt_host, self._cfg.mqtt_port, self._cfg.mqtt_keepalive_s,
        )
        self._client.loop_start()

    def stop(self):
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    def publish(self, topic: str, payload: bytes) -> bool:
        info = self._client.publish(topic, payload, qos=0, retain=False)
        return info.rc == mqtt.MQTT_ERR_SUCCESS


# --- Payload formatters ---


def _grid_payload(reading: dict, sign: int) -> bytes:
    p = reading["power"] * sign
    i = reading["current"] * sign
    obj = {
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
    return json.dumps(obj).encode("utf-8")


def _pv_payload(reading: dict, sign: int) -> bytes:
    p = reading["power"] * sign
    i = reading["current"] * sign
    # When sign flips the CT, lifetime production accumulates in the SDM120's
    # "export" register instead of "import".
    energy_forward = reading["energy_forward"] if sign >= 0 else reading["energy_reverse"]
    obj = {
        "pv": {
            "power": round(p, 2),
            "voltage": round(reading["voltage"], 2),
            "current": round(i, 3),
            "energy_forward": round(energy_forward, 3),
            "L1": {
                "power": round(p, 2),
                "voltage": round(reading["voltage"], 2),
                "current": round(i, 3),
                "frequency": round(reading["frequency"], 3),
                "energy_forward": round(energy_forward, 3),
            },
        }
    }
    return json.dumps(obj).encode("utf-8")


def _payload_for(meter: MeterConfig, reading: dict) -> bytes:
    if meter.role == "grid":
        return _grid_payload(reading, meter.power_sign)
    if meter.role == "pv":
        return _pv_payload(reading, meter.power_sign)
    raise ValueError(f"unknown role: {meter.role}")


# --- Main loop ---


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = Config.from_env()

    bus = SDM120Bus(cfg)
    bridge = MqttBridge(cfg)
    bridge.start()

    stop = False
    def _shutdown(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("bridge running: period=%.1fs meters=%s",
             cfg.publish_period_s,
             [(m.name, m.slave_addr, m.role, m.topic) for m in cfg.meters])
    next_tick = time.monotonic()
    consecutive_bus_errors = 0

    while not stop:
        for meter in cfg.meters:
            try:
                reading = bus.read_all(meter.slave_addr)
                payload = _payload_for(meter, reading)
                ok = bridge.publish(meter.topic, payload)
                if ok:
                    log.debug("%s: published %s", meter.name, payload.decode())
                    consecutive_bus_errors = 0
                else:
                    log.warning("%s: publish enqueue failed", meter.name)
            except Exception as e:
                consecutive_bus_errors += 1
                log.warning("%s: read/publish error (%d in a row): %s",
                            meter.name, consecutive_bus_errors, e)
                if consecutive_bus_errors >= 5:
                    log.warning("repeated failures; closing serial for reopen")
                    bus.close()
                    consecutive_bus_errors = 0

        next_tick += cfg.publish_period_s
        slack = next_tick - time.monotonic()
        if slack > 0:
            time.sleep(slack)
        else:
            next_tick = time.monotonic()

    log.info("shutting down")
    bridge.stop()
    bus.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
