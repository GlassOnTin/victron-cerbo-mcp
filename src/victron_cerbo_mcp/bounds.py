"""Hard-coded safety bounds for write tools.

These guard against an LLM (or a typo) writing values outside what's safe
for *this* installation: a MultiPlus II 48/3000/35-32, a SmartSolar MPPT
150/35, and an ECO-Worthy 100 Ah / 48 V battery.

Tighten further if your install has more conservative limits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NumericBounds:
    minimum: float
    maximum: float

    def check(self, value: float, name: str) -> float:
        if not (self.minimum <= value <= self.maximum):
            raise ValueError(
                f"{name}={value} outside allowed range "
                f"[{self.minimum}, {self.maximum}]"
            )
        return float(value)


# --- numeric bounds ----------------------------------------------------------

# MultiPlus II 48/3000: 3000 VA inverter rating sets the practical envelope
# for grid setpoint in either direction.
GRID_SETPOINT_W = NumericBounds(-3000, 3000)

# ESS BatteryLife minimum SoC: never below 10 % (battery damage risk).
MIN_SOC_PCT = NumericBounds(10, 100)

# AC input current limit, MultiPlus rated to 32 A AC input.
INPUT_CURRENT_LIMIT_A = NumericBounds(0, 32)

# DVCC system max charge current. ECO-Worthy 100 Ah pack: 0.5 C = 50 A is the
# safe ceiling; the BMS will limit to its own max anyway, but enforce here too.
DVCC_MAX_CHARGE_A = NumericBounds(0, 50)

# SmartSolar MPPT 150/35: hardware rated to 35 A.
MPPT_CHARGE_CURRENT_A = NumericBounds(0, 35)

# Victron EV Charger NS: device-reported range on this install is 6–13 A
# (driven by the EVCS's own Iin_max=13 A setting, and a hard 6 A minimum
# from the J1772/Type-2 pilot signal duty-cycle floor).
EVCHARGER_CURRENT_A = NumericBounds(6, 13)


# --- enum allowed sets (string IDs the lib accepts in .set()) ---------------

ESS_MODE_VALUES = {"phase_compensation_enabled", "phase_compensation_disabled", "external_control"}
MULTIPLUS_MODE_VALUES = {"charger_only", "inverter_only", "on", "off"}
EVCHARGER_MODE_VALUES = {"manual", "auto", "scheduled_charge"}
SWITCH_VALUES = {"on", "off"}
RELAY_INDEXES = {0, 1}
