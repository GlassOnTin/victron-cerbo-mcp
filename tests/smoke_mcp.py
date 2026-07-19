"""Spawn the MCP server over stdio and call its tools.

Validates the full FastMCP wire protocol round-trip, not just the bridge.
Run with:
    CERBO_MQTT_PASSWORD=... uv run python tests/smoke_mcp.py
"""

import asyncio
import json
import os

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main() -> None:
    transport = StdioTransport(
        command="uv",
        args=["run", "victron-cerbo-mcp"],
        env={
            "CERBO_MQTT_PASSWORD": os.environ["CERBO_MQTT_PASSWORD"],
            "VICTRON_HOST": os.environ.get("VICTRON_HOST", "venus.local"),
            "VICTRON_READ_ONLY": "true",
            "PATH": os.environ["PATH"],
        },
    )
    async with Client(transport) as session:
        tools = await session.list_tools()
        print(f"\n[tools] {len(tools)} registered:")
        for t in tools:
            print(f"  - {t.name}: {(t.description or '').splitlines()[0][:80]}")

        print("\n[call] system_overview")
        r = await session.call_tool("system_overview", {})
        payload = r.data.model_dump() if hasattr(r.data, "model_dump") else r.data
        print(json.dumps(payload, indent=2, default=str))

        print("\n[call] list_devices")
        r = await session.call_tool("list_devices", {})
        devs = r.data if isinstance(r.data, list) else getattr(r.data, "result", r.data)
        if isinstance(devs, list):
            print(f"  {len(devs)} devices")
            for d in devs[:7]:
                name = getattr(d, "name", None) if not isinstance(d, dict) else d.get("name")
                dt = getattr(d, "device_type", None) if not isinstance(d, dict) else d.get("device_type")
                print(f"  - {dt}: {name}")
        else:
            print(devs)


if __name__ == "__main__":
    asyncio.run(main())
