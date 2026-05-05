"""MCP server entrypoint.

Starts the Victron MQTT bridge under FastMCP's lifespan, then runs over stdio.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from . import tools_read, tools_write
from .bridge import BridgeConfig, VictronBridge


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict]:
    cfg = BridgeConfig.from_env()
    bridge = VictronBridge(cfg)
    await bridge.connect()
    try:
        yield {"bridge": bridge}
    finally:
        await bridge.close()


def _build_server() -> FastMCP:
    mcp = FastMCP("victron-cerbo", lifespan=_lifespan)
    tools_read.register(mcp)
    # Write tools are still registered in read-only mode; they'll refuse with a
    # clear error from the bridge. Registering them keeps the tool surface
    # discoverable so users see what's available.
    tools_write.register(mcp)
    return mcp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    _build_server().run()


if __name__ == "__main__":
    main()
