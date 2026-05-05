"""Inspect writable metrics to understand the .set() value contract."""

import asyncio
from victron_cerbo_mcp.bridge import BridgeConfig, VictronBridge


async def main() -> None:
    b = VictronBridge(BridgeConfig.from_env())
    await b.connect()
    try:
        for m in b.iter_metrics():
            if type(m).__name__ != "WritableMetric":
                continue
            kind = getattr(m, "metric_kind", None)
            kindv = kind.value if kind is not None else None
            ev = getattr(m, "enum_values", None)
            mn, mx, st = getattr(m, "min_value", None), getattr(m, "max_value", None), getattr(m, "step", None)
            print(f"{m.short_id:<45s}  kind={kindv:<8}  cur={m.formatted_value!r}")
            if ev:
                print(f"  enum_values: {ev}")
            if mn is not None or mx is not None:
                print(f"  range: min={mn} max={mx} step={st}")
    finally:
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
