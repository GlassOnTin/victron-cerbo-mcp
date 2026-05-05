"""Manual live smoke test — connect to the Cerbo and dump a snapshot.

Not run by pytest. Invoke as:
    CERBO_MQTT_PASSWORD=... uv run python tests/smoke_live.py
"""

import asyncio
import json
from victron_cerbo_mcp.bridge import BridgeConfig, VictronBridge


async def main() -> None:
    cfg = BridgeConfig.from_env()
    print(f"connecting to {cfg.host}:{cfg.port} ssl={cfg.use_ssl} read_only={cfg.read_only}")
    b = VictronBridge(cfg)
    await b.connect()
    try:
        devices = b.device_summary()
        ids = b.list_metric_ids()
        print(f"\ndevices ({len(devices)}):")
        for d in devices:
            print(f"  {d['unique_id']}  type={d['device_type']}  metrics={d['metric_count']}")
        print(f"\ntotal metrics: {len(ids)}")
        print("first 30 unique_ids:")
        for uid in ids[:30]:
            print(f"  {uid}")
        # Sample some likely-interesting suffixes
        for suffix in ["battery_soc", "battery_voltage", "battery_temperature",
                       "solarcharger_yield_power", "solarcharger_yield_today",
                       "vebus_state", "vebus_mode"]:
            matches = [u for u in ids if u.endswith(suffix)]
            if matches:
                m = b.get_metric(matches[0])
                print(f"\n  {matches[0]} = {m.value!r}  unit={getattr(m,'unit_of_measurement',None)}")
    finally:
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
