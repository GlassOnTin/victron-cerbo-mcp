"""Async wrapper around victron_mqtt.Hub.

Owns the single long-lived connection to the Cerbo's MQTT broker, holds the
in-memory metric cache (which the underlying Hub maintains for us), and
serialises writes through a single lock.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import victron_mqtt
from victron_mqtt import Hub

log = logging.getLogger(__name__)


def _coerce_value(v: Any) -> Any:
    """Convert victron_mqtt enum values to their string form for JSON serialisation."""
    if hasattr(v, "string"):  # GenericOnOff and similar enum-likes carry .string
        return v.string
    if hasattr(v, "value") and not isinstance(v, (int, float, str, bool)):
        return v.value
    return v


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class BridgeConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    use_ssl: bool
    installation_id: str | None
    read_only: bool

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        host = os.environ.get("VICTRON_HOST", "venus.local")
        port = int(os.environ.get("VICTRON_PORT", "8883"))
        password = (
            os.environ.get("VICTRON_PASSWORD")
            or os.environ.get("CERBO_MQTT_PASSWORD")
        )
        username = os.environ.get("VICTRON_USERNAME")
        use_ssl = _env_bool("VICTRON_USE_SSL", default=(port == 8883))
        installation_id = os.environ.get("VICTRON_PORTAL_ID")
        read_only = _env_bool("VICTRON_READ_ONLY", default=True)
        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            use_ssl=use_ssl,
            installation_id=installation_id,
            read_only=read_only,
        )


class VictronBridge:
    """Single shared Hub + write lock + small helpers."""

    def __init__(self, cfg: BridgeConfig):
        self.cfg = cfg
        self.hub: Hub | None = None
        self._write_lock = asyncio.Lock()

    @property
    def read_only(self) -> bool:
        return self.cfg.read_only

    async def connect(self) -> None:
        log.info(
            "connecting host=%s port=%s ssl=%s read_only=%s",
            self.cfg.host, self.cfg.port, self.cfg.use_ssl, self.cfg.read_only,
        )
        self.hub = Hub(
            host=self.cfg.host,
            port=self.cfg.port,
            username=self.cfg.username,
            password=self.cfg.password,
            use_ssl=self.cfg.use_ssl,
            installation_id=self.cfg.installation_id,
        )
        await self.hub.connect()
        await self.hub.wait_for_first_refresh()
        log.info("connected, devices=%d", len(self.hub.devices))

    async def close(self) -> None:
        if self.hub is not None:
            await self.hub.disconnect()
            self.hub = None

    # ------------- read helpers -------------

    def require_hub(self) -> Hub:
        if self.hub is None:
            raise RuntimeError("bridge is not connected")
        return self.hub

    def get_metric(self, unique_id: str) -> Any | None:
        """Return the victron_mqtt Metric object, or None if not seen yet."""
        return self.require_hub().get_metric(unique_id)

    def get_value(self, unique_id: str, default: Any = None) -> Any:
        m = self.get_metric(unique_id)
        return _coerce_value(m.value) if m is not None else default

    def iter_metrics(self) -> Any:
        """Yield every Metric across every Device. ``device.metrics`` is a list."""
        for dev in self.require_hub().devices.values():
            for metric in dev.metrics:
                yield metric

    def list_metric_ids(self) -> list[str]:
        return sorted(m.unique_id for m in self.iter_metrics())

    def device_summary(self) -> list[dict[str, Any]]:
        hub = self.require_hub()
        out = []
        for unique, dev in hub.devices.items():
            dt = getattr(dev, "device_type", None)
            # device_type is an Enum whose value is a tuple ("system", "Victron Venus");
            # surface just the short label.
            if dt is not None and hasattr(dt, "value"):
                dt = dt.value
            if isinstance(dt, (tuple, list)) and dt:
                dt = dt[0]
            out.append({
                "unique_id": unique,
                "device_type": dt,
                "name": getattr(dev, "name", None),
                "model": getattr(dev, "model", None),
                "manufacturer": getattr(dev, "manufacturer", None),
                "instance": getattr(dev, "device_id", None),
                "metric_count": len(dev.metrics),
            })
        return out

    def find_metric_by_short_id(self, short_id: str) -> Any | None:
        """Return the first Metric whose ``short_id`` exactly matches."""
        for m in self.iter_metrics():
            if getattr(m, "short_id", None) == short_id:
                return m
        return None

    def get_value_by_short_id(self, short_id: str, default: Any = None) -> Any:
        m = self.find_metric_by_short_id(short_id)
        return _coerce_value(m.value) if m is not None else default

    # ------------- write helper -------------

    async def write_metric(self, unique_id: str, value: Any) -> Any:
        """Set a writable metric by unique_id; return post-write read-back."""
        m = self.get_metric(unique_id)
        if m is None:
            raise KeyError(f"metric not found: {unique_id}")
        return await self._write(m, value)

    async def write_by_short_id(self, short_id: str, value: Any) -> Any:
        """Set a writable metric by short_id; return post-write read-back."""
        m = self.find_metric_by_short_id(short_id)
        if m is None:
            raise KeyError(f"metric not found: {short_id}")
        return await self._write(m, value)

    async def _write(self, m: Any, value: Any) -> Any:
        if self.read_only:
            raise PermissionError(
                "bridge is in read-only mode (set VICTRON_READ_ONLY=false to enable writes)"
            )
        if not isinstance(m, victron_mqtt.WritableMetric):
            raise TypeError(f"metric is not writable: {m.short_id}")
        # For switches/selects, validate against the lib's declared enum_values
        # so we fail fast rather than via an obscure broker error.
        ev = getattr(m, "enum_values", None)
        if ev and isinstance(value, str) and value not in ev:
            raise ValueError(
                f"{m.short_id}: {value!r} not in enum_values {ev}"
            )
        async with self._write_lock:
            m.set(value)
            # Allow the broker round-trip to settle.
            await asyncio.sleep(0.5)
            return _coerce_value(m.value)
