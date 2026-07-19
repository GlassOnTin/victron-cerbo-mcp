"""End-to-end test of the streamable-http transport.

Boots the server in HTTP mode with auth disabled (so the test doesn't need a
real OAuth provider) and a stubbed bridge that fakes a single device. The
test then connects via fastmcp.Client over HTTP and exercises list_devices.

Auth wiring is exercised separately in test_auth_unit (token allowlist) and
during the trycloudflare.com pre-prod run before deployment.
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest
from fastmcp import Client, FastMCP

from victron_cerbo_mcp import tools_read
from victron_cerbo_mcp.auth import AllowlistedGitHubProvider


class _StubBridge:
    """Just enough surface for tools_read.list_devices / list_metrics."""

    def device_summary(self):
        return [{
            "unique_id": "system_0",
            "device_type": "system",
            "name": "stub GX",
            "model": "stub",
            "manufacturer": "test",
            "instance": 0,
            "metric_count": 0,
        }]

    def iter_metrics(self):
        return iter([])

    def list_metric_ids(self):
        return []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _http_server() -> AsyncIterator[str]:
    """Spin up the server in HTTP mode with no auth and a stubbed bridge."""

    @asynccontextmanager
    async def lifespan(server: FastMCP):
        yield {"bridge": _StubBridge()}

    mcp = FastMCP("victron-cerbo-test", lifespan=lifespan)
    tools_read.register(mcp)

    port = _free_port()
    server_task = asyncio.create_task(
        mcp.run_http_async(host="127.0.0.1", port=port, show_banner=False),
        name="test-http-server",
    )
    # Poll until the listener is up (server.run_http_async starts uvicorn async).
    for _ in range(50):
        await asyncio.sleep(0.1)
        try:
            with socket.socket() as s:
                s.settimeout(0.1)
                s.connect(("127.0.0.1", port))
                break
        except OSError:
            continue
    else:
        server_task.cancel()
        raise RuntimeError("http server failed to bind within 5s")

    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_streamable_http_list_devices():
    async with _http_server() as url:
        async with Client(url) as c:
            tools = await c.list_tools()
            names = {t.name for t in tools}
            assert "list_devices" in names
            assert "system_overview" in names

            r = await c.call_tool("list_devices", {})
            assert hasattr(r, "data")
            payload = r.data if isinstance(r.data, list) else r.data.result
            assert payload
            # Each entry is a Pydantic model with attribute access.
            assert any(getattr(d, "unique_id", None) == "system_0" for d in payload)


def test_allowlisted_provider_requires_logins():
    import pytest as _pt
    with _pt.raises(ValueError):
        AllowlistedGitHubProvider(
            client_id="x", client_secret="y",
            base_url="https://example.com",
            allowed_logins=set(),
        )
