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
