"""CLI utility to query live Victron sensor telemetry."""

import json
import sys
import urllib.request
from pathlib import Path


def main() -> None:
    # 1. Try local HTTP endpoint
    data = None
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8766/sensors", timeout=1.5)
        if req.status == 200:
            data = json.loads(req.read().decode("utf-8"))
    except Exception:
        pass

    # 2. Fallback to /dev/shm or ~/.local/state
    if not data:
        for p in (
            Path("/dev/shm/victron_sensors.json"),
            Path.home() / ".local" / "state" / "victron_sensors.json",
        ):
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass

    if not data:
        print("Error: Victron Sensor Daemon is not running. Start with:", file=sys.stderr)
        print("  systemctl --user start victron-sensor-daemon.service", file=sys.stderr)
        sys.exit(1)

    if "--json" in sys.argv:
        print(json.dumps(data, indent=2))
        return

    b = data.get("battery", {})
    s = data.get("solar", {})
    m = data.get("multiplus", {})
    g = data.get("grid", {})
    sys_d = data.get("system", {})
    alarms = data.get("alarms", [])

    print("═══════════════════════════════════════════════════════════")
    print(f"  Victron Cerbo GX Status ({data.get('status', 'unknown').upper()})")
    print("═══════════════════════════════════════════════════════════")
    print("🔋 BATTERY (Eco-Worthy UP16S Bank):")
    soc = b.get("soc_pct", "--")
    soh = b.get("soh_pct", "--")
    p_w = b.get("power_w", 0)
    c_a = b.get("current_a", 0)
    v_v = b.get("voltage_v", 0)
    sign = "+" if p_w >= 0 else ""
    flow = "Charging" if p_w > 10 else ("Discharging" if p_w < -10 else "Idle")
    print(f"   SoC: {soc}% | SoH: {soh}% | State: {flow} ({sign}{p_w:.0f} W / {sign}{c_a:.1f} A)")
    print(f"   Voltage: {v_v:.2f} V | Temp: {b.get('temperature_c', '--')} °C")
    print(f"   Cell Min/Max: {b.get('min_cell_v', '--')} V / {b.get('max_cell_v', '--')} V (Δ {b.get('cell_imbalance_mv', '--')} mV)")
    print(f"   Modules Online: {b.get('modules_online', '--')}/3 ({b.get('installed_capacity_ah', 300)} Ah)")

    print("\n☀️  SOLAR MPPT (SmartSolar 150/45):")
    print(f"   Live Yield: {s.get('power_w', 0):.0f} W (PV: {s.get('pv_voltage_v', '--')} V / {s.get('pv_current_a', '--')} A)")
    print(f"   Today Yield: {s.get('yield_today_kwh', '--')} kWh | Peak Today: {s.get('max_power_today_w', '--')} W")
    print(f"   Yesterday: {s.get('yield_yesterday_kwh', '--')} kWh | Total: {s.get('yield_total_kwh', '--')} kWh")

    print("\n⚡ MULTIPLUS-II:")
    print(f"   State: {m.get('state', '--')} | Mode: {m.get('mode', '--')}")
    print(f"   AC Output: {m.get('output_power_w', 0):.0f} W | AC Input: {m.get('input_power_w', 0):.0f} W ({m.get('input_voltage_v', '--')} V)")
    print(f"   DC Conversion: {m.get('dc_power_w', '--')} W ({m.get('dc_current_a', '--')} A)")

    print("\n🌐 GRID & HOUSE:")
    g_w = g.get("power_w", 0)
    g_label = "Importing" if g_w > 10 else ("Exporting" if g_w < -10 else "Balanced")
    print(f"   Grid Power: {abs(g_w):.0f} W ({g_label}) | Mains: {g.get('voltage_v', '--')} V")
    print(f"   House Consumption: {sys_d.get('consumption_power_w', '--')} W")

    if alarms:
        print("\n⚠️  ACTIVE ALARMS:")
        for a in alarms:
            print(f"   - {a}")
    else:
        print("\n✅ Alarms: None (All systems normal)")
    print("═══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
