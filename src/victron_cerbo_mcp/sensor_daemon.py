"""Victron Sensor Adapter Daemon.

Connects to the Cerbo GX MQTT broker, periodically aggregates telemetry
from the battery BMS, MPPT solar charger, MultiPlus inverter, grid meter,
and system aggregator, then publishes structured snapshots to:
  1. `/dev/shm/victron_sensors.json` (fast in-memory file)
  2. `~/.local/state/victron_sensors.json` (persistent user state fallback)
  3. Built-in HTTP endpoint on http://127.0.0.1:8766/sensors for KDE Plasma widgets

Designed to run as a systemd user service:
  systemctl --user start victron-sensor-daemon.service
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bridge import BridgeConfig, VictronBridge

log = logging.getLogger("victron_sensor_daemon")

DEFAULT_SHM_PATH = Path("/dev/shm/victron_sensors.json")
DEFAULT_STATE_PATH = Path.home() / ".local" / "state" / "victron_sensors.json"
DEFAULT_INTERVAL_S = 1.0
DEFAULT_HTTP_PORT = 8766


def _coerce(val: Any) -> Any:
    """Coerce Victron MQTT enum-like objects to serializable types."""
    if hasattr(val, "string"):
        return val.string
    if hasattr(val, "value") and not isinstance(val, (int, float, str, bool)):
        return val.value
    return val


class SensorPublisher:
    """Aggregates sensor metrics and publishes to shared memory / HTTP / filesystem."""

    def __init__(
        self,
        bridge: VictronBridge,
        shm_path: Path = DEFAULT_SHM_PATH,
        state_path: Path = DEFAULT_STATE_PATH,
        interval_s: float = DEFAULT_INTERVAL_S,
        http_port: int = DEFAULT_HTTP_PORT,
    ):
        self.bridge = bridge
        self.shm_path = shm_path
        self.state_path = state_path
        self.interval_s = interval_s
        self.http_port = http_port
        self._stop_event = asyncio.Event()
        self._latest_snapshot: dict[str, Any] | None = None

    def build_snapshot(self) -> dict[str, Any]:
        hub = self.bridge.hub
        connected = self.bridge.connected and bool(getattr(hub, "devices", None))

        now_iso = datetime.now(timezone.utc).isoformat()
        now_ts = time.time()

        if not connected or hub is None:
            return {
                "status": "offline",
                "connected": False,
                "timestamp": now_iso,
                "timestamp_unix": now_ts,
                "error": "Connecting to Cerbo GX broker...",
                "battery": {},
                "solar": {},
                "multiplus": {},
                "grid": {},
                "system": {},
                "alarms": [],
            }

        g = self.bridge.get_value_by_short_id

        # Battery metrics (battery_512 or primary battery)
        min_cell_v = g("battery_min_cell_voltage")
        max_cell_v = g("battery_max_cell_voltage")
        cell_imbalance_mv = (
            round((max_cell_v - min_cell_v) * 1000.0, 1)
            if min_cell_v is not None and max_cell_v is not None
            else None
        )

        battery = {
            "soc_pct": g("battery_soc"),
            "soh_pct": g("battery_soh"),
            "voltage_v": g("battery_voltage"),
            "current_a": g("battery_current"),
            "power_w": g("battery_power"),
            "temperature_c": g("battery_temperature"),
            "min_cell_v": min_cell_v,
            "max_cell_v": max_cell_v,
            "cell_imbalance_mv": cell_imbalance_mv,
            "min_cell_id": _coerce(g("battery_min_voltage_cell_id")),
            "max_cell_id": _coerce(g("battery_max_voltage_cell_id")),
            "min_cell_temp_c": g("battery_min_cell_temperature"),
            "max_cell_temp_c": g("battery_max_cell_temperature"),
            "installed_capacity_ah": g("battery_installed_capacity"),
            "modules_online": g("battery_nr_modules_online"),
            "modules_offline": g("battery_nr_modules_offline"),
            "max_charge_current_a": g("battery_max_charge_current"),
            "max_discharge_current_a": g("battery_max_discharge_current"),
            "is_charging": (g("battery_current") or 0.0) > 0.1,
            "is_discharging": (g("battery_current") or 0.0) < -0.1,
        }

        # Solar charger metrics (solarcharger_280 / MPPT)
        solar = {
            "power_w": g("solarcharger_yield_power"),
            "yield_today_kwh": g("solarcharger_yield_today"),
            "yield_yesterday_kwh": g("solarcharger_yield_yesterday"),
            "yield_total_kwh": g("solarcharger_yield_total"),
            "max_power_today_w": g("solarcharger_max_power_today"),
            "pv_voltage_v": g("solarcharger_voltage"),
            "pv_current_a": g("solarcharger_dc_current"),
            "mppt_mode": _coerce(g("solarcharger_mppt_operation_mode")),
            "state": _coerce(g("solarcharger_state")),
            "is_producing": (g("solarcharger_yield_power") or 0.0) > 5.0,
        }

        # MultiPlus / VE.Bus inverter metrics (vebus_276)
        multiplus = {
            "state": _coerce(g("vebus_inverter_state")),
            "mode": _coerce(g("vebus_inverter_mode")),
            "input_power_w": g("vebus_inverter_input_power_l1") or g("vebus_device_0_input_power_l1"),
            "output_power_w": g("vebus_inverter_output_power_l1") or g("vebus_device_0_output_power_l1"),
            "input_voltage_v": g("vebus_inverter_input_voltage_l1"),
            "output_voltage_v": g("vebus_inverter_output_voltage_l1"),
            "input_frequency_hz": g("vebus_inverter_input_frequency_l1"),
            "output_frequency_hz": g("vebus_inverter_output_frequency_l1"),
            "dc_power_w": g("vebus_inverter_dc_power"),
            "dc_current_a": g("vebus_inverter_dc_current"),
            "dc_voltage_v": g("vebus_inverter_dc_voltage"),
        }

        # Grid metrics (grid_100 / dbus-mqtt-grid)
        grid_power = g("system_grid_power_l1")
        if grid_power is None:
            grid_power = g("grid_power_l1")

        grid = {
            "power_w": grid_power,
            "voltage_v": g("grid_voltage_l1") or g("vebus_inverter_input_voltage_l1"),
            "current_a": g("grid_current_l1"),
            "frequency_hz": g("grid_frequency"),
            "is_importing": (grid_power or 0.0) > 10.0,
            "is_exporting": (grid_power or 0.0) < -10.0,
        }

        # System & ESS aggregator
        system = {
            "consumption_power_w": g("system_consumption_power_l1"),
            "grid_setpoint_w": g("system_ac_power_set_point"),
            "ess_mode": _coerce(g("system_ess_mode")),
            "relay_1": _coerce(g("switchable_output_0_state")),
            "relay_2": _coerce(g("switchable_output_1_state")),
        }

        # Active alarms
        alarms: list[str] = []
        for m in self.bridge.iter_metrics():
            sid = getattr(m, "short_id", "") or ""
            if "alarm" not in sid or "_setting_" in sid:
                continue
            v = m.value
            vstr = str(v).lower() if v is not None else ""
            if vstr and "no alarm" not in vstr and vstr not in ("0", "ok", "off", "no_alarm"):
                alarms.append(f"{sid}: {vstr}")

        return {
            "status": "online",
            "connected": True,
            "timestamp": now_iso,
            "timestamp_unix": now_ts,
            "battery": battery,
            "solar": solar,
            "multiplus": multiplus,
            "grid": grid,
            "system": system,
            "alarms": alarms,
        }

    def _write_atomic(self, target_path: Path, data_str: str) -> None:
        """Write file atomically using a temporary file in the same directory."""
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=target_path.parent, prefix="victron_sensors_", suffix=".tmp"
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(data_str)
            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, target_path)
        except Exception as e:
            log.warning("failed atomic write to %s: %r", target_path, e)

    def publish_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._latest_snapshot = snapshot
        data_str = json.dumps(snapshot, indent=2, ensure_ascii=False)
        # 1. Fast shared memory (/dev/shm)
        if self.shm_path.parent.exists():
            self._write_atomic(self.shm_path, data_str)
        # 2. Local state dir (~/.local/state)
        self._write_atomic(self.state_path, data_str)

    async def _handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Lightweight HTTP server responding to GET /sensors or GET /."""
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            while True:
                h = await asyncio.wait_for(reader.readline(), timeout=1.0)
                if not h or h in (b"\r\n", b"\n"):
                    break
            snapshot = self._latest_snapshot or self.build_snapshot()
            body = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Cache-Control: no-cache\r\n"
                b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                b"Connection: close\r\n"
                b"\r\n" + body
            )
            writer.write(resp)
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def run(self) -> None:
        log.info("Starting Victron Sensor Publisher (interval=%.1fs, http=127.0.0.1:%d)", self.interval_s, self.http_port)
        http_server = await asyncio.start_server(self._handle_http, "127.0.0.1", self.http_port)
        await self.bridge.connect()
        try:
            while not self._stop_event.is_set():
                snapshot = self.build_snapshot()
                self.publish_snapshot(snapshot)
                await asyncio.sleep(self.interval_s)
        finally:
            log.info("Stopping Victron Sensor Publisher...")
            http_server.close()
            await http_server.wait_closed()
            offline_snapshot = {
                "status": "offline",
                "connected": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "timestamp_unix": time.time(),
                "error": "Daemon stopped",
                "battery": {},
                "solar": {},
                "multiplus": {},
                "grid": {},
                "system": {},
                "alarms": [],
            }
            self.publish_snapshot(offline_snapshot)
            await self.bridge.close()

    def stop(self) -> None:
        self._stop_event.set()


async def _async_main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    cfg = BridgeConfig.from_env()
    bridge = VictronBridge(cfg)
    publisher = SensorPublisher(bridge)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, publisher.stop)

    await publisher.run()


def main() -> None:
    try:
        asyncio.run(_async_main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
