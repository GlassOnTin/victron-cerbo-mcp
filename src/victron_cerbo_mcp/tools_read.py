"""Read tools.

These return small, summarised JSON objects — one tool per "view" the user
typically asks about. The escape hatch ``metric_get`` lets Claude reach for
any value when the curated tools don't cover it.

Short_ids used here were validated against a Cerbo GX running Venus OS Large
v3.80~14 with a SmartSolar MPPT 150/35, MultiPlus II, and ECO-Worthy 48V/100Ah
battery on CAN. They live under each device's ``metrics`` list with a stable
key like ``battery_soc``, ``solarcharger_yield_power``, etc.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from .bridge import VictronBridge
from .schema import DeviceInfo, GridStatus, SystemOverview


def _bridge(ctx: Context) -> VictronBridge:
    return ctx.request_context.lifespan_context["bridge"]


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def system_overview(ctx: Context) -> SystemOverview:
        """Single-shot snapshot of battery, solar, AC and ESS state.

        Combines values from the battery BMS, the solar charger, the
        MultiPlus (vebus), and the system-level aggregator.
        """
        b = _bridge(ctx)
        g = b.get_value_by_short_id

        # Active alarms: any sensor metric whose short_id contains "alarm" with a
        # non-OK value. Exclude "_setting_" alarms (those are user toggles for
        # whether to alarm, not active alarms).
        alarms: list[str] = []
        for m in b.iter_metrics():
            sid = getattr(m, "short_id", "") or ""
            if "alarm" not in sid or "_setting_" in sid:
                continue
            kind = getattr(m, "metric_kind", None)
            if kind is not None and getattr(kind, "value", None) != "sensor":
                continue
            v = m.value
            vstr = str(v).lower() if v is not None else ""
            if vstr and "no alarm" not in vstr and vstr not in ("0", "ok", "off"):
                alarms.append(f"{sid}={vstr}")

        return SystemOverview(
            battery_soc_pct=g("battery_soc"),
            battery_voltage_v=g("battery_voltage"),
            battery_current_a=g("battery_current"),
            battery_power_w=g("battery_power"),
            battery_temperature_c=g("battery_temperature"),
            battery_min_cell_v=g("battery_min_cell_voltage"),
            battery_max_cell_v=g("battery_max_cell_voltage"),
            pv_power_w=g("solarcharger_yield_power"),
            pv_yield_today_kwh=g("solarcharger_yield_today"),
            ac_in_power_w=g("system_grid_power_l1"),
            ac_out_power_w=g("vebus_device_0_output_power_l1") or g("vebus_inverter_output_power_l1"),
            ac_consumption_w=g("system_consumption_power_l1"),
            multiplus_state=g("vebus_inverter_state"),
            multiplus_mode=g("vebus_inverter_mode"),
            grid_setpoint_w=g("system_ac_power_set_point"),
            ess_mode=g("system_ess_mode"),
            active_alarms=alarms,
        )

    @mcp.tool()
    async def list_devices(ctx: Context) -> list[DeviceInfo]:
        """List every Victron device the broker is currently exposing."""
        return [DeviceInfo(**d) for d in _bridge(ctx).device_summary()]

    @mcp.tool()
    async def list_metrics(ctx: Context, device: str | None = None) -> list[dict[str, Any]]:
        """Return every metric, optionally filtered by device unique_id (e.g. "battery_512").

        Each entry has unique_id, short_id, name, value, formatted, unit, kind, writable.
        """
        b = _bridge(ctx)
        out = []
        for m in b.iter_metrics():
            uid = m.unique_id
            if device and not uid.startswith(device + "_") and uid != device:
                continue
            out.append({
                "unique_id": uid,
                "short_id": getattr(m, "short_id", None),
                "name": getattr(m, "name", None),
                "value": str(m.value) if m.value is not None else None,
                "formatted": getattr(m, "formatted_value", None),
                "unit": getattr(m, "unit_of_measurement", None),
                "kind": str(getattr(m, "metric_kind", "")) or None,
                "writable": type(m).__name__ == "WritableMetric",
            })
        return out

    @mcp.tool()
    async def grid_status(ctx: Context) -> GridStatus:
        """Live grid meter snapshot from com.victronenergy.grid (any instance).

        Backed by the dbus-mqtt-grid driver on the Cerbo, which subscribes to
        the JSON published by the workshop's SDM120 bridge. Returns power
        (signed, +ve = importing), L1 voltage / current, and lifetime
        forward/reverse energy counters.

        If no grid device is found (driver not running, or no MQTT data yet),
        ``found`` is False.
        """
        b = _bridge(ctx)
        g = b.get_value_by_short_id

        # Find the grid device's unique_id for context.
        grid_device_uid = None
        for d in b.device_summary():
            if (d.get("device_type") or "").lower() == "grid":
                grid_device_uid = d["unique_id"]
                break

        if grid_device_uid is None:
            return GridStatus(
                found=False,
                note="no com.victronenergy.grid device on dbus — check dbus-mqtt-grid service on Cerbo",
            )

        return GridStatus(
            found=True,
            power_w=g("grid_power"),
            power_l1_w=g("grid_power_l1"),
            voltage_l1_v=g("grid_voltage_l1"),
            current_l1_a=g("grid_current_l1"),
            energy_forward_kwh=g("grid_energy_forward"),
            energy_reverse_kwh=g("grid_energy_reverse"),
            phases=g("system_grid_phases"),
            device_unique_id=grid_device_uid,
        )

    @mcp.tool()
    async def metric_get(ctx: Context, unique_id: str) -> dict[str, Any]:
        """Read a single metric by unique_id (e.g. ``battery_512_battery_soc``)."""
        b = _bridge(ctx)
        m = b.get_metric(unique_id)
        if m is None:
            return {"unique_id": unique_id, "found": False}
        return {
            "unique_id": unique_id,
            "found": True,
            "value": str(m.value) if m.value is not None else None,
            "formatted": getattr(m, "formatted_value", None),
            "unit": getattr(m, "unit_of_measurement", None),
            "kind": str(getattr(m, "metric_kind", "")) or None,
            "writable": type(m).__name__ == "WritableMetric",
        }
