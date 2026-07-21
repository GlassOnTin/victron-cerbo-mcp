"""Bounds validation — pure Python, no network."""

import pytest

from victron_cerbo_mcp import bounds


# ---------- numeric bounds ----------

def test_grid_setpoint_in_range():
    assert bounds.GRID_SETPOINT_W.check(0, "w") == 0.0
    assert bounds.GRID_SETPOINT_W.check(-3000, "w") == -3000.0
    assert bounds.GRID_SETPOINT_W.check(3000, "w") == 3000.0


@pytest.mark.parametrize("value", [-3001, 3001, 99999])
def test_grid_setpoint_out_of_range(value):
    with pytest.raises(ValueError):
        bounds.GRID_SETPOINT_W.check(value, "w")


def test_min_soc_floor_protects_battery():
    with pytest.raises(ValueError):
        bounds.MIN_SOC_PCT.check(5, "pct")
    bounds.MIN_SOC_PCT.check(10, "pct")
    bounds.MIN_SOC_PCT.check(100, "pct")


def test_input_current_limit_negative_rejected():
    with pytest.raises(ValueError):
        bounds.INPUT_CURRENT_LIMIT_A.check(-1, "a")
    bounds.INPUT_CURRENT_LIMIT_A.check(0, "a")
    bounds.INPUT_CURRENT_LIMIT_A.check(32, "a")
    with pytest.raises(ValueError):
        bounds.INPUT_CURRENT_LIMIT_A.check(33, "a")


def test_dvcc_max_charge_capped_at_half_c():
    bounds.DVCC_MAX_CHARGE_A.check(50, "a")
    with pytest.raises(ValueError):
        bounds.DVCC_MAX_CHARGE_A.check(51, "a")


def test_mppt_charge_current_capped_at_35():
    bounds.MPPT_CHARGE_CURRENT_A.check(35, "a")
    with pytest.raises(ValueError):
        bounds.MPPT_CHARGE_CURRENT_A.check(36, "a")


def test_max_charge_power_envelope():
    # 0 (no AC charging) and 3000 (Multi envelope) are the bounds; -1 (no limit)
    # is a sentinel handled in the tool, not by check().
    bounds.MAX_CHARGE_POWER_W.check(0, "w")
    bounds.MAX_CHARGE_POWER_W.check(3000, "w")
    with pytest.raises(ValueError):
        bounds.MAX_CHARGE_POWER_W.check(-1, "w")
    with pytest.raises(ValueError):
        bounds.MAX_CHARGE_POWER_W.check(3001, "w")


def test_max_feed_in_power_envelope():
    bounds.MAX_FEED_IN_POWER_W.check(0, "w")
    bounds.MAX_FEED_IN_POWER_W.check(3000, "w")
    with pytest.raises(ValueError):
        bounds.MAX_FEED_IN_POWER_W.check(-1, "w")
    with pytest.raises(ValueError):
        bounds.MAX_FEED_IN_POWER_W.check(3001, "w")


def test_schedule_bounds():
    bounds.SCHEDULE_DURATION_MIN.check(0, "m")
    bounds.SCHEDULE_DURATION_MIN.check(1440, "m")
    with pytest.raises(ValueError):
        bounds.SCHEDULE_DURATION_MIN.check(1441, "m")
    bounds.SCHEDULE_SOC_PCT.check(0, "s")
    bounds.SCHEDULE_SOC_PCT.check(100, "s")
    with pytest.raises(ValueError):
        bounds.SCHEDULE_SOC_PCT.check(101, "s")


def test_evcharger_current_j1772_floor_and_iin_max_ceiling():
    bounds.EVCHARGER_CURRENT_A.check(6, "a")
    bounds.EVCHARGER_CURRENT_A.check(13, "a")
    with pytest.raises(ValueError):
        bounds.EVCHARGER_CURRENT_A.check(5, "a")
    with pytest.raises(ValueError):
        bounds.EVCHARGER_CURRENT_A.check(14, "a")


# ---------- enum sets ----------

def test_ess_mode_set_complete():
    assert bounds.ESS_MODE_VALUES == {
        "phase_compensation_enabled",
        "phase_compensation_disabled",
        "external_control",
    }


def test_multiplus_mode_set_complete():
    assert bounds.MULTIPLUS_MODE_VALUES == {
        "charger_only", "inverter_only", "on", "off",
    }


def test_evcharger_mode_set_complete():
    assert bounds.EVCHARGER_MODE_VALUES == {
        "manual", "auto", "scheduled_charge",
    }


def test_switch_values():
    assert bounds.SWITCH_VALUES == {"on", "off"}
    assert bounds.RELAY_INDEXES == {0, 1}


def test_dess_mode_values():
    # 'off' is the "never export battery" setting; must be present.
    assert "off" in bounds.DESS_MODE_VALUES
    assert bounds.DESS_MODE_VALUES == {"off", "auto_vrm", "buy", "sell", "node_red"}


def test_schedule_day_values_have_enable_and_disable():
    assert {"every_day", "weekdays", "weekends"} <= bounds.SCHEDULE_DAY_VALUES
    assert {"disabled_every_day", "disabled_weekdays"} <= bounds.SCHEDULE_DAY_VALUES
    assert bounds.SCHEDULE_SLOTS == {0, 1, 2, 3, 4}


# ---------- HH:MM parsing ----------

def test_parse_hhmm():
    from victron_cerbo_mcp.tools_write import _parse_hhmm

    assert _parse_hhmm("20:00") == 1200
    assert _parse_hhmm("00:00") == 0
    assert _parse_hhmm("23:59") == 1439
    for bad in ["24:00", "12:60", "8", "8:00pm", "-1:00"]:
        with pytest.raises(ValueError):
            _parse_hhmm(bad)


# ---------- tool registration (no network) ----------

async def test_write_tools_registered():
    from fastmcp import FastMCP

    from victron_cerbo_mcp import tools_write

    m = FastMCP("test")
    tools_write.register(m)
    names = {t.name for t in await m.list_tools()}
    assert {
        "set_max_charge_power",
        "set_max_feed_in_power",
        "set_dess_mode",
        "set_scheduled_charge",
    } <= names
