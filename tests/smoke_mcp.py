"""Spawn the MCP server over stdio and call its tools.

Validates the full FastMCP wire protocol round-trip, not just the bridge.
Run with:
    CERBO_MQTT_PASSWORD=... uv run python tests/smoke_mcp.py
"""

import asyncio
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command="uv",
        args=["run", "victron-cerbo-mcp"],
        env={
            "CERBO_MQTT_PASSWORD": os.environ["CERBO_MQTT_PASSWORD"],
            "VICTRON_HOST": os.environ.get("VICTRON_HOST", "venus.local"),
            "VICTRON_READ_ONLY": "true",
            # Inherit PATH so 'uv' resolves; pass through.
            "PATH": os.environ["PATH"],
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"\n[tools] {len(tools.tools)} registered:")
            for t in tools.tools:
                print(f"  - {t.name}: {(t.description or '').splitlines()[0][:80]}")

            def _join(r) -> str:
                return "".join(c.text for c in r.content if hasattr(c, "text"))

            print("\n[call] system_overview")
            r = await session.call_tool("system_overview", {})
            try:
                print(json.dumps(json.loads(_join(r)), indent=2))
            except Exception:
                print(_join(r))

            print("\n[call] list_devices")
            r = await session.call_tool("list_devices", {})
            try:
                devs = json.loads(_join(r))
                if isinstance(devs, dict):
                    devs = [devs]
                for d in devs:
                    dt = d.get("device_type") or ""
                    print(f"  {d['unique_id']:<25} {dt:<20} metrics={d['metric_count']}")
            except Exception:
                print(_join(r))


if __name__ == "__main__":
    asyncio.run(main())
