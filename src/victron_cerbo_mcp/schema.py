"""Pydantic models for tool inputs and outputs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WriteResult(BaseModel):
    """Returned by every write tool."""

    unique_id: str
    requested_value: Any
    readback_value: Any
    note: str | None = None


class SystemOverview(BaseModel):
    battery_soc_pct: float | None = None
    battery_voltage_v: float | None = None
    battery_current_a: float | None = None
    battery_power_w: float | None = None
    battery_temperature_c: float | None = None
    battery_min_cell_v: float | None = None
    battery_max_cell_v: float | None = None
    pv_power_w: float | None = None
    pv_yield_today_kwh: float | None = None
    ac_in_power_w: float | None = None
    ac_out_power_w: float | None = None
    ac_consumption_w: float | None = None
    multiplus_state: str | None = None
    multiplus_mode: str | None = None
    grid_setpoint_w: float | None = None
    ess_mode: str | None = None
    active_alarms: list[str] = Field(default_factory=list)


class DeviceInfo(BaseModel):
    unique_id: str
    device_type: str | None = None
    name: str | None = None
    model: str | None = None
    instance: int | None = None
    metric_count: int = 0


class GridStatus(BaseModel):
    """Snapshot of the grid meter exposed via com.victronenergy.grid.

    Sign convention (Victron's): power > 0 = importing from grid;
    power < 0 = exporting to grid (surplus solar etc).
    """

    found: bool = True
    power_w: float | None = None
    power_l1_w: float | None = None
    voltage_l1_v: float | None = None
    current_l1_a: float | None = None
    energy_forward_kwh: float | None = None
    energy_reverse_kwh: float | None = None
    phases: int | None = None
    device_unique_id: str | None = None
    note: str | None = None
