"""Tests for the sensor daemon and publisher."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from victron_cerbo_mcp.bridge import BridgeConfig, VictronBridge
from victron_cerbo_mcp.sensor_daemon import SensorPublisher


def test_build_snapshot_offline():
    cfg = BridgeConfig(
        host="fake.local",
        port=8883,
        username=None,
        password="pwd",
        use_ssl=True,
        installation_id=None,
        read_only=True,
    )
    bridge = VictronBridge(cfg)
    publisher = SensorPublisher(bridge)
    snapshot = publisher.build_snapshot()
    assert snapshot["status"] == "offline"
    assert snapshot["connected"] is False
    assert "error" in snapshot


def test_build_snapshot_online(tmp_path):
    cfg = BridgeConfig(
        host="fake.local",
        port=8883,
        username=None,
        password="pwd",
        use_ssl=True,
        installation_id=None,
        read_only=True,
    )
    bridge = VictronBridge(cfg)
    bridge.hub = MagicMock()
    bridge.hub.connected = True
    bridge.hub.devices = {"battery_512": MagicMock(), "solarcharger_280": MagicMock()}

    def fake_get(sid):
        mapping = {
            "battery_soc": 85.0,
            "battery_soh": 100.0,
            "battery_voltage": 53.5,
            "battery_current": 10.0,
            "battery_power": 535.0,
            "battery_min_cell_voltage": 3.340,
            "battery_max_cell_voltage": 3.345,
            "solarcharger_yield_power": 600.0,
            "solarcharger_yield_today": 2.5,
            "system_grid_power_l1": -150.0,
        }
        return mapping.get(sid)

    bridge.get_value_by_short_id = fake_get
    bridge.iter_metrics = lambda: []

    shm_file = tmp_path / "shm.json"
    state_file = tmp_path / "state.json"
    publisher = SensorPublisher(bridge, shm_path=shm_file, state_path=state_file)
    snapshot = publisher.build_snapshot()

    assert snapshot["status"] == "online"
    assert snapshot["connected"] is True
    assert snapshot["battery"]["soc_pct"] == 85.0
    assert snapshot["battery"]["cell_imbalance_mv"] == 5.0
    assert snapshot["solar"]["power_w"] == 600.0
    assert snapshot["grid"]["is_exporting"] is True

    publisher.publish_snapshot(snapshot)
    assert shm_file.exists()
    assert state_file.exists()
