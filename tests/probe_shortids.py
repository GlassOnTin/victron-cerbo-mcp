"""Dump short_id -> value for every metric, grouped by device.

Used as a one-off to map summary tools to actual library names.
"""

import asyncio
from victron_cerbo_mcp.bridge import BridgeConfig, VictronBridge


async def main() -> None:
    b = VictronBridge(BridgeConfig.from_env())
    await b.connect()
    try:
        hub = b.require_hub()
        for dev_id, dev in hub.devices.items():
            print(f"\n=== {dev_id}  ({dev.device_type}, {dev.model})  metrics={len(dev.metrics)} ===")
            for m in sorted(dev.metrics, key=lambda x: x.short_id):
                kind = getattr(m, "metric_kind", None)
                kindv = kind.value if kind is not None else None
                wr = "W" if type(m).__name__ == "WritableMetric" else " "
                v = m.value
                vstr = m.formatted_value if m.formatted_value else repr(v)
                print(f"  [{wr}] {m.short_id:<45s} {kindv:<10}  = {vstr}")
    finally:
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
