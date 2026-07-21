"""Write tools.

Every tool:
  * is rejected by the bridge if ``VICTRON_READ_ONLY=true`` (the default),
  * requires an explicit ``confirm=True`` argument from the caller,
  * validates input against ``bounds.py`` before sending,
  * returns the post-write read-back value.

Short_ids are validated against Venus OS Large v3.80~14 with the user's
specific kit; they may differ on other firmwares. If a tool reports
"metric not found" first, run ``list_metrics`` to check the live name.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from . import bounds
from .bridge import VictronBridge
from .schema import WriteResult


def _bridge(ctx: Context) -> VictronBridge:
    return ctx.request_context.lifespan_context["bridge"]


def _require_confirm(confirm: bool, action: str) -> None:
    if not confirm:
        raise ValueError(
            f"refusing to {action} without confirm=True (safety guard)"
        )


def _parse_hhmm(s: str) -> int:
    """'HH:MM' (24h) -> minutes since midnight. The schedule metric takes
    minutes and the library converts to the dbus seconds itself."""
    try:
        hh, mm = s.split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError):
        raise ValueError(f"start must be 'HH:MM' 24-hour, got {s!r}")
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"start out of range (00:00-23:59): {s!r}")
    return h * 60 + m


async def _do_write(
    ctx: Context, short_id: str, value, requested_for_response=None
) -> WriteResult:
    b = _bridge(ctx)
    readback, note = await b.write_by_short_id(short_id, value)
    return WriteResult(
        unique_id=short_id,
        requested_value=requested_for_response if requested_for_response is not None else value,
        readback_value=readback,
        note=note,
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def set_grid_setpoint(
        ctx: Context, watts: float, confirm: bool = False
    ) -> WriteResult:
        """ESS grid power setpoint (W). Negative = export, positive = import.

        Bounds: ±3000 W (MultiPlus II 48/3000 rating). Requires confirm=True.
        """
        _require_confirm(confirm, "set grid setpoint")
        bounds.GRID_SETPOINT_W.check(watts, "watts")
        return await _do_write(ctx, "system_ac_power_set_point", watts)

    @mcp.tool()
    async def set_minimum_soc(
        ctx: Context, percent: float, confirm: bool = False
    ) -> WriteResult:
        """ESS BatteryLife minimum SoC (%). Allowed: 10–100 in steps of 5."""
        _require_confirm(confirm, "set minimum SoC")
        bounds.MIN_SOC_PCT.check(percent, "percent")
        return await _do_write(ctx, "system_ess_min_soc_limit", percent)

    @mcp.tool()
    async def set_ess_mode(
        ctx: Context, mode: str, confirm: bool = False
    ) -> WriteResult:
        """ESS mode.

        One of:
          * "phase_compensation_enabled"
          * "phase_compensation_disabled"
          * "external_control"
        """
        _require_confirm(confirm, "set ESS mode")
        if mode not in bounds.ESS_MODE_VALUES:
            raise ValueError(f"mode must be one of {sorted(bounds.ESS_MODE_VALUES)}")
        return await _do_write(ctx, "system_ess_mode", mode)

    @mcp.tool()
    async def set_dess_mode(
        ctx: Context, mode: str, confirm: bool = False
    ) -> WriteResult:
        """Dynamic ESS (DESS) mode.

        One of: "off", "auto_vrm", "buy", "sell", "node_red".
          * "off"      — plain ESS self-consumption; **never exports the
                         battery** to the grid.
          * "auto_vrm" — DESS trades against VRM price schedules and **can
                         discharge the battery to the grid**.
          * "buy"/"sell"/"node_red" — other DESS control sources.
        Requires confirm=True.
        """
        _require_confirm(confirm, "set DESS mode")
        if mode not in bounds.DESS_MODE_VALUES:
            raise ValueError(f"mode must be one of {sorted(bounds.DESS_MODE_VALUES)}")
        return await _do_write(ctx, "system_settings_dess_mode", mode)

    @mcp.tool()
    async def set_scheduled_charge(
        ctx: Context,
        slot: int,
        start: str | None = None,
        duration_min: int | None = None,
        soc: int | None = None,
        days: str | None = None,
        confirm: bool = False,
    ) -> list[WriteResult]:
        """Configure an ESS BatteryLife scheduled-charge slot (0-4).

        Only the fields you pass are changed:
          * start        — "HH:MM" (24-hour, local)
          * duration_min — minutes (0-1440)
          * soc          — target SoC %, 0-100
          * days         — one of: every_day, weekdays, weekends,
                           monday..sunday, or a disabled_* id to disable the
                           slot (e.g. "disabled_every_day")
        Returns one WriteResult per field changed. Requires confirm=True.
        """
        _require_confirm(confirm, "set scheduled charge")
        if slot not in bounds.SCHEDULE_SLOTS:
            raise ValueError(f"slot must be one of {sorted(bounds.SCHEDULE_SLOTS)}")
        results: list[WriteResult] = []
        base = f"system_ess_schedule_charge_{slot}"
        if days is not None:
            if days not in bounds.SCHEDULE_DAY_VALUES:
                raise ValueError(
                    f"days must be one of {sorted(bounds.SCHEDULE_DAY_VALUES)}"
                )
            results.append(await _do_write(ctx, f"{base}_days", days))
        if start is not None:
            results.append(
                await _do_write(
                    ctx, f"{base}_start", _parse_hhmm(start),
                    requested_for_response=start,
                )
            )
        if duration_min is not None:
            bounds.SCHEDULE_DURATION_MIN.check(duration_min, "duration_min")
            results.append(await _do_write(ctx, f"{base}_duration", int(duration_min)))
        if soc is not None:
            bounds.SCHEDULE_SOC_PCT.check(soc, "soc")
            results.append(await _do_write(ctx, f"{base}_soc", int(soc)))
        if not results:
            raise ValueError(
                "nothing to set: provide at least one of start / duration_min / soc / days"
            )
        return results

    @mcp.tool()
    async def set_multiplus_mode(
        ctx: Context, mode: str, confirm: bool = False
    ) -> WriteResult:
        """MultiPlus mode.

        One of: "charger_only", "inverter_only", "on", "off".
        """
        _require_confirm(confirm, "set MultiPlus mode")
        if mode not in bounds.MULTIPLUS_MODE_VALUES:
            raise ValueError(
                f"mode must be one of {sorted(bounds.MULTIPLUS_MODE_VALUES)}"
            )
        return await _do_write(ctx, "vebus_inverter_mode", mode)

    @mcp.tool()
    async def set_input_current_limit(
        ctx: Context, amps: float, confirm: bool = False
    ) -> WriteResult:
        """MultiPlus AC input current limit (A). Bounds: 0–32."""
        _require_confirm(confirm, "set input current limit")
        bounds.INPUT_CURRENT_LIMIT_A.check(amps, "amps")
        return await _do_write(ctx, "vebus_inverter_current_limit", amps)

    @mcp.tool()
    async def set_dvcc_max_charge_current(
        ctx: Context, amps: float, confirm: bool = False
    ) -> WriteResult:
        """DVCC system max charge current (A). Bounds: 0–50 (0.5C of 100 Ah pack).

        Use -1 to disable the DVCC limit (battery BMS handles).
        """
        _require_confirm(confirm, "set DVCC max charge current")
        if amps != -1:
            bounds.DVCC_MAX_CHARGE_A.check(amps, "amps")
        return await _do_write(ctx, "system_ess_max_charge_current", amps)

    @mcp.tool()
    async def set_max_charge_power(
        ctx: Context, watts: float, confirm: bool = False
    ) -> WriteResult:
        """ESS max charge power (W) — the AC-side battery-charging limit.

        Controls how much the MultiPlus will charge the battery from AC (grid
        AND AC-coupled PV surplus):
          *  0  — no AC-side charging (AC-PV surplus spills to grid instead of
                  being stored)
          * -1  — no limit (store all available surplus)
          * 0-3000 W — explicit cap
        DC-coupled MPPT charging is NOT limited by this. Requires confirm=True.
        """
        _require_confirm(confirm, "set ESS max charge power")
        if watts != -1:
            bounds.MAX_CHARGE_POWER_W.check(watts, "watts")
        return await _do_write(ctx, "system_ess_max_charge_power", watts)

    @mcp.tool()
    async def set_max_feed_in_power(
        ctx: Context, watts: float, confirm: bool = False
    ) -> WriteResult:
        """ESS max grid feed-in / export power (W).

          *  0  — never export (no feed-in at all)
          * -1  — no limit (export the overflow once the battery is full)
          * 0-3000 W — explicit cap
        Only excess *solar* is exported once the battery is full; plain ESS
        never exports the battery itself regardless of this value. Requires
        confirm=True.
        """
        _require_confirm(confirm, "set ESS max feed-in power")
        if watts != -1:
            bounds.MAX_FEED_IN_POWER_W.check(watts, "watts")
        return await _do_write(ctx, "system_ess_max_feed_in_power", watts)

    @mcp.tool()
    async def set_mppt_charge_current_limit(
        ctx: Context, amps: float, confirm: bool = False
    ) -> WriteResult:
        """SmartSolar MPPT charge current limit (A). Bounds: 0–35 (MPPT 150/35)."""
        _require_confirm(confirm, "set MPPT charge current limit")
        bounds.MPPT_CHARGE_CURRENT_A.check(amps, "amps")
        return await _do_write(ctx, "solarcharger_charge_current_limit", amps)

    @mcp.tool()
    async def set_relay(
        ctx: Context, index: int, state: str, confirm: bool = False
    ) -> WriteResult:
        """Cerbo on-board relay 0 or 1. State: "on" (closed) or "off" (open)."""
        _require_confirm(confirm, "toggle relay")
        if index not in bounds.RELAY_INDEXES:
            raise ValueError("relay index must be 0 or 1")
        if state not in bounds.SWITCH_VALUES:
            raise ValueError("state must be 'on' or 'off'")
        return await _do_write(ctx, f"system_relay_{index}", state)

    @mcp.tool()
    async def set_mppt_enabled(
        ctx: Context, enabled: bool, confirm: bool = False
    ) -> WriteResult:
        """Enable or disable the SmartSolar MPPT (master on/off)."""
        _require_confirm(confirm, "toggle MPPT")
        return await _do_write(
            ctx, "solarcharger_mode", "on" if enabled else "off",
            requested_for_response=enabled,
        )

    @mcp.tool()
    async def set_evcharger_mode(
        ctx: Context, mode: str, confirm: bool = False
    ) -> WriteResult:
        """Victron EV Charger NS mode.

        One of:
          * "manual"           — fixed setpoint, ignores solar surplus
          * "auto"             — modulates with ESS solar surplus
          * "scheduled_charge" — follows the charger's schedule
        """
        _require_confirm(confirm, "set EV charger mode")
        if mode not in bounds.EVCHARGER_MODE_VALUES:
            raise ValueError(
                f"mode must be one of {sorted(bounds.EVCHARGER_MODE_VALUES)}"
            )
        return await _do_write(ctx, "evcharger_mode", mode)

    @mcp.tool()
    async def set_evcharger_charge(
        ctx: Context, enabled: bool, confirm: bool = False
    ) -> WriteResult:
        """Start or stop EV charging (Manual-mode start/stop switch)."""
        _require_confirm(confirm, "toggle EV charger")
        return await _do_write(
            ctx, "evcharger_charge", "on" if enabled else "off",
            requested_for_response=enabled,
        )

    @mcp.tool()
    async def set_evcharger_current(
        ctx: Context, amps: float, confirm: bool = False
    ) -> WriteResult:
        """EV Charger current setpoint (A). Bounds: 6–13 (J1772 floor / Iin_max)."""
        _require_confirm(confirm, "set EV charger current")
        bounds.EVCHARGER_CURRENT_A.check(amps, "amps")
        return await _do_write(ctx, "evcharger_set_current", int(amps))

    @mcp.tool()
    async def set_evcharger_auto_start(
        ctx: Context, enabled: bool, confirm: bool = False
    ) -> WriteResult:
        """Auto-start charging when a vehicle is plugged in."""
        _require_confirm(confirm, "toggle EV charger auto-start")
        return await _do_write(
            ctx, "evcharger_auto_start", "on" if enabled else "off",
            requested_for_response=enabled,
        )
