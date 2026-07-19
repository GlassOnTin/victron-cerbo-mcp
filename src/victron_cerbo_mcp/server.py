"""MCP server entrypoint.

Starts the Victron MQTT bridge under FastMCP's lifespan, then runs over either
stdio (default — for Claude Code as a local subprocess) or streamable-http
(for hosting as a Claude.ai Custom Connector).

Env switches:
  VICTRON_TRANSPORT       "stdio" (default) or "http"
  VICTRON_HTTP_HOST       default "0.0.0.0" (http only)
  VICTRON_HTTP_PORT       default 8765      (http only)
  VICTRON_READ_ONLY_MODE  "true" hides write tools from the tool list entirely
                          (distinct from VICTRON_READ_ONLY which gates writes
                          at the bridge layer with a runtime PermissionError).
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from . import tools_read, tools_write
from .bridge import BridgeConfig, VictronBridge


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


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
    transport = os.environ.get("VICTRON_TRANSPORT", "stdio").strip().lower()
    read_only_mode = _env_bool("VICTRON_READ_ONLY_MODE", default=False)

    auth = None
    if transport == "http":
        from .auth import build_auth
        auth = build_auth()

    mcp = FastMCP("victron-cerbo", lifespan=_lifespan, auth=auth)
    tools_read.register(mcp)
    if not read_only_mode:
        # Write tools are still gated at the bridge layer by VICTRON_READ_ONLY;
        # registering them keeps the tool surface discoverable. Set
        # VICTRON_READ_ONLY_MODE=true on the mobile Connector to hide them.
        tools_write.register(mcp)
    return mcp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    transport = os.environ.get("VICTRON_TRANSPORT", "stdio").strip().lower()
    mcp = _build_server()
    if transport == "stdio":
        mcp.run()
    elif transport == "http":
        host = os.environ.get("VICTRON_HTTP_HOST", "0.0.0.0")
        port = int(os.environ.get("VICTRON_HTTP_PORT", "8765"))
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        raise SystemExit(
            f"VICTRON_TRANSPORT={transport!r} not supported; use 'stdio' or 'http'"
        )


if __name__ == "__main__":
    main()
