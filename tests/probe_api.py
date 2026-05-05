"""Throwaway: introspect the actual victron_mqtt API shapes against live broker."""

import asyncio
from victron_cerbo_mcp.bridge import BridgeConfig, VictronBridge


async def main() -> None:
    b = VictronBridge(BridgeConfig.from_env())
    await b.connect()
    try:
        hub = b.require_hub()
        print(f"hub.devices type: {type(hub.devices).__name__}")
        # try as dict first, fallback to list
        if isinstance(hub.devices, dict):
            items = list(hub.devices.items())
        else:
            items = [(getattr(d, "unique_id", repr(d)), d) for d in hub.devices]
        print(f"device count: {len(items)}\n")
        for key, dev in items[:3]:
            print(f"  device key: {key}")
            print(f"    type:       {type(dev).__name__}")
            print(f"    attrs:      {[a for a in dir(dev) if not a.startswith('_')][:20]}")
            print(f"    metrics:    type={type(dev.metrics).__name__}")
            ms = dev.metrics if not isinstance(dev.metrics, dict) else list(dev.metrics.values())
            print(f"    metric n:   {len(ms)}")
            if ms:
                m = ms[0]
                print(f"    first metric type: {type(m).__name__}")
                print(f"    first metric attrs: {[a for a in dir(m) if not a.startswith('_')][:25]}")
                for attr in ["unique_id", "name", "value", "formatted_value",
                             "unit_of_measurement", "metric_kind", "metric_type",
                             "short_id", "key", "topic"]:
                    if hasattr(m, attr):
                        print(f"      .{attr} = {getattr(m, attr)!r}")
            print()
    finally:
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
