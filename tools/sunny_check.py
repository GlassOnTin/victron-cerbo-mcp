#!/usr/bin/env python
"""Sunny-day energy-policy check (read-only).

Verifies the 2026-07-21 policy under sun:
  1. STORE   — roof-PV surplus charges the battery (not exported) while SoC<100.
  2. NO EARLY GRID-CHARGE — battery charges from solar, not grid import.
  3. NEVER   — battery is never discharging while the grid exports.

Run any midday with sun:
    cd ~/Code/victron-cerbo-mcp && uv run python tools/sunny_check.py

Reads the Cerbo password from ~/.claude.json; connects READ-ONLY.
Exit code: 0 = pass, 1 = fail, 2 = inconclusive/unreachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys


def _password() -> str | None:
    d = json.load(open(os.path.expanduser("~/.claude.json")))

    def f(o):
        if isinstance(o, dict):
            if "victron-cerbo" in o.get("mcpServers", {}):
                return o["mcpServers"]["victron-cerbo"]["env"].get("CERBO_MQTT_PASSWORD")
            for v in o.values():
                r = f(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = f(v)
                if r:
                    return r
        return None

    return f(d)


async def main() -> int:
    logging.disable(logging.CRITICAL)
    os.environ.setdefault("VICTRON_HOST", "192.168.0.208")
    os.environ["VICTRON_READ_ONLY"] = "true"
    if not os.environ.get("CERBO_MQTT_PASSWORD"):
        os.environ["CERBO_MQTT_PASSWORD"] = _password() or ""

    from victron_cerbo_mcp.bridge import BridgeConfig, VictronBridge

    b = VictronBridge(BridgeConfig.from_env())
    await b.connect()
    for _ in range(90):
        if b._healthy():
            break
        await asyncio.sleep(1)
    if not b._healthy():
        print("UNREACHABLE: Cerbo link not healthy (try again / check the Cerbo)")
        return 2

    g = b.get_value_by_short_id
    soc = g("battery_soc") or 0.0
    bcur = g("battery_current") or 0.0            # + = charging, - = discharging
    pv_ac = g("pvinverter_power_total") or 0.0    # roof, AC-coupled
    pv_dc = g("solarcharger_yield_power") or 0.0  # DC MPPT
    grid = g("grid_power") or 0.0                 # + = import, - = export
    dess = g("system_settings_dess_mode")
    maxchg = g("system_ess_max_charge_power")
    await b.close()

    pv = float(pv_ac) + float(pv_dc)
    print(
        f"SoC={soc:.0f}%  batt={bcur:+.0f}A  PV={pv:.0f}W (roof {pv_ac:.0f} + mppt {pv_dc:.0f})  "
        f"grid={grid:+.0f}W  DESS={dess}  MaxChargePower={maxchg}"
    )

    verdict, rc = [], 0

    # (3) battery must never export
    if bcur < -1 and grid < -100:
        verdict.append("FAIL: battery discharging while grid exports — battery→grid dump")
        rc = 1

    if pv < 200:
        print("INCONCLUSIVE: PV < 200 W (overcast / not enough sun). Re-run at a sunnier midday.")
        return 2 if rc == 0 else rc

    # sun is producing
    if soc < 99:
        if bcur > 1 and grid > -150:
            verdict.append("PASS: solar surplus is charging the battery, not exporting (storing)")
        elif grid < -300 and bcur <= 1:
            verdict.append(
                "FAIL: exporting solar to grid while battery < 100% and NOT charging — "
                "MaxChargePower change may not have taken (expected -1)"
            )
            rc = 1
        else:
            verdict.append(f"UNCLEAR: SoC<100 but batt={bcur:+.0f}A grid={grid:+.0f}W — inspect")
        # (2) no early grid-charge: charging hard while importing hard and PV low
        if bcur > 5 and grid > 500 and pv < bcur * 40:
            verdict.append("WARN: battery charging from GRID import, not solar (early grid-charge?)")
    else:
        if grid < -50:
            verdict.append("PASS: battery full (100%), overflow solar exporting — expected")
        else:
            verdict.append("OK: battery full, no export right now")

    print("VERDICT:")
    for line in verdict:
        print(f"  - {line}")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
