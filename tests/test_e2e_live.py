"""End-to-end live test — talks to a real Cerbo over MQTT.

Gated on env: only runs if VICTRON_LIVE=1 (and CERBO_MQTT_PASSWORD is set).
Read-only checks plus safety-rail checks — does NOT mutate the Cerbo.

Run:
    VICTRON_LIVE=1 CERBO_MQTT_PASSWORD=... uv run pytest tests/test_e2e_live.py -v
"""

from __future__ import annotations

import json
import os

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


pytestmark = pytest.mark.skipif(
    os.environ.get("VICTRON_LIVE") != "1",
    reason="set VICTRON_LIVE=1 to run live integration tests",
)


def _params() -> StdioServerParameters:
    return StdioServerParameters(
        command="uv",
        args=["run", "victron-cerbo-mcp"],
        env={
            "CERBO_MQTT_PASSWORD": os.environ["CERBO_MQTT_PASSWORD"],
            "VICTRON_HOST": os.environ.get("VICTRON_HOST", "venus.local"),
            "VICTRON_READ_ONLY": "true",
            "PATH": os.environ["PATH"],
        },
    )


def _join(result) -> str:
    return "".join(c.text for c in result.content if hasattr(c, "text"))


async def test_lists_expected_tools():
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
    expected = {
        "system_overview", "list_devices", "list_metrics", "metric_get",
        "grid_status",
        "set_grid_setpoint", "set_minimum_soc", "set_ess_mode",
        "set_multiplus_mode", "set_input_current_limit",
        "set_dvcc_max_charge_current", "set_mppt_charge_current_limit",
        "set_relay", "set_mppt_enabled",
    }
    missing = expected - names
    assert not missing, f"missing tools: {missing}"


async def test_system_overview_returns_battery_soc():
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            result = await s.call_tool("system_overview", {})
    payload = json.loads(_join(result))
    assert payload["battery_soc_pct"] is not None
    assert 0 <= payload["battery_soc_pct"] <= 100


async def test_grid_status_returns_voltage():
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            result = await s.call_tool("grid_status", {})
    payload = json.loads(_join(result))
    assert payload["found"] is True, f"grid device not found: {payload}"
    # Even with no CT clamp fitted, voltage_l1_v should be a real mains
    # reading and energy/power counters should exist (may be 0).
    assert payload["voltage_l1_v"] is not None
    assert 200 < payload["voltage_l1_v"] < 260


async def test_metric_get_known_short_id():
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            result = await s.call_tool(
                "metric_get", {"unique_id": "battery_512_battery_soc"}
            )
    payload = json.loads(_join(result))
    assert payload["found"] is True
    assert payload["unit"] == "%"


async def test_set_relay_refuses_without_confirm():
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            result = await s.call_tool("set_relay", {"index": 0, "state": "off"})
    text = _join(result).lower()
    assert "confirm" in text, f"expected confirm-required error, got: {text!r}"


async def test_set_relay_blocked_in_read_only_mode():
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            result = await s.call_tool(
                "set_relay", {"index": 0, "state": "off", "confirm": True}
            )
    text = _join(result).lower()
    assert "read-only" in text or "readonly" in text, (
        f"expected read-only error, got: {text!r}"
    )
