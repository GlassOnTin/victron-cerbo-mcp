"""Bridge robustness against Cerbo outages / power cuts.

Unit tests (always run) cover the health logic and non-fatal startup. A live
test (gated on VICTRON_LIVE=1) reproduces the "connected but all-null" failure
against a real Cerbo and asserts the supervisor auto-recovers with no manual
reconnect.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from victron_cerbo_mcp.bridge import (
    BridgeConfig,
    BridgeReconnecting,
    VictronBridge,
    _STALE_AFTER_S,
)


def _cfg(**over) -> BridgeConfig:
    base = dict(
        host="192.0.2.1", port=8883, username=None, password="x",
        use_ssl=True, installation_id=None, read_only=True,
    )
    base.update(over)
    return BridgeConfig(**base)


class _FakeHub:
    """Minimal stand-in for victron_mqtt.Hub for health-logic tests."""

    def __init__(self, *, connected=True, devices=None, last_publish="recent"):
        self.connected = connected
        self.devices = {"system_0": object()} if devices is None else devices
        if last_publish == "recent":
            self._last_full_publish_called = time.monotonic()
        elif last_publish == "stale":
            self._last_full_publish_called = time.monotonic() - (_STALE_AFTER_S + 60)
        elif last_publish is not None:
            self._last_full_publish_called = last_publish
        # last_publish=None -> attribute absent (library-change fallback path)


# --------------------------- health logic (unit) ---------------------------

def test_healthy_false_when_no_hub():
    b = VictronBridge(_cfg())
    assert b.hub is None
    assert b._healthy() is False


def test_healthy_false_when_socket_down():
    b = VictronBridge(_cfg())
    b.hub = _FakeHub(connected=False)
    assert b._healthy() is False


def test_healthy_false_when_no_devices():
    # The exact all-null symptom: socket up, but nothing enumerated.
    b = VictronBridge(_cfg())
    b.hub = _FakeHub(connected=True, devices={})
    assert b._healthy() is False


def test_healthy_false_when_stale():
    b = VictronBridge(_cfg())
    b.hub = _FakeHub(connected=True, last_publish="stale")
    assert b._healthy() is False


def test_healthy_true_when_connected_fresh_with_devices():
    b = VictronBridge(_cfg())
    b.hub = _FakeHub(connected=True, last_publish="recent")
    assert b._healthy() is True


def test_healthy_falls_back_to_socket_when_timestamp_absent():
    # If the library drops _last_full_publish_called, we degrade to conn+devices.
    b = VictronBridge(_cfg())
    b.hub = _FakeHub(connected=True, last_publish=None)
    assert b._healthy() is True


def test_require_hub_raises_when_unhealthy():
    b = VictronBridge(_cfg())
    b.hub = _FakeHub(connected=True, devices={})
    with pytest.raises(BridgeReconnecting):
        b.require_hub()


# --------------------------- non-fatal startup (unit) ----------------------

async def test_connect_is_nonfatal_when_cerbo_unreachable():
    """A power outage at startup must not kill the server; the supervisor runs."""
    b = VictronBridge(_cfg())

    async def _boom():
        raise ConnectionError("cerbo down")

    b._open_hub = _boom  # type: ignore[method-assign]
    await b.connect()  # must NOT raise
    try:
        assert b.hub is None
        assert b._supervisor_task is not None
        assert b._healthy() is False
    finally:
        await b.close()


# --------------------------- live recovery (gated) -------------------------

async def _wait_healthy(b: VictronBridge, timeout_s: float) -> bool:
    """Poll for health. Fresh connects to a real Cerbo are flaky (the broker may
    return an incomplete snapshot or time out), so recovery can take a couple of
    supervisor rebuild cycles — that's exactly the self-healing under test."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if b._healthy():
            return True
        await asyncio.sleep(1)
    return b._healthy()


@pytest.mark.skipif(
    os.environ.get("VICTRON_LIVE") != "1",
    reason="set VICTRON_LIVE=1 (and CERBO_MQTT_PASSWORD) to run live recovery test",
)
async def test_live_supervisor_auto_recovers_from_stale():
    cfg = BridgeConfig.from_env()
    cfg.read_only = True  # never mutate the Cerbo from a test
    b = VictronBridge(cfg)
    await b.connect()
    try:
        # connect() is non-fatal and the first snapshot can be empty/slow; the
        # supervisor rebuilds until the link is genuinely serving data.
        assert await _wait_healthy(b, 150), "did not reach a healthy state"
        assert len(b.require_hub().devices) > 0

        # Reproduce the observed failure: connected socket, but data has gone
        # stale (Cerbo reboot / MQTT restart) -> reads would return all-null.
        b.hub._last_full_publish_called = time.monotonic() - (_STALE_AFTER_S + 100)
        assert not b._healthy()
        with pytest.raises(BridgeReconnecting):
            b.require_hub()

        # Supervisor must rebuild the hub on its own, no manual reconnect.
        assert await _wait_healthy(b, 150), "supervisor failed to auto-recover"
        assert len(b.require_hub().devices) > 0
    finally:
        await b.close()
