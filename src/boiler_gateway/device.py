"""Device adapter: the only code that talks to the boiler's controller (ADR 0002).

One long-lived, Noise-encrypted connection to the ESPHome native API, kept up
by the library's reconnect logic. The adapter caches every state update with
the time it arrived, so readers can tell fresh values from stale ones (P2).

ESPHome sends a state when it changes, and a full set on (re)connect. A
value's age therefore grows while it stays the same: an old value is still
current as long as the connection is up. Readers treat "not connected" as
stale, not "old" (`updated_at` is when the value last changed).

The `Device` protocol is the seam for a later split into a separate service
(ADR 0002, option 3). This increment is read-only: the adapter has no method
that sends a command to the device.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol

from aioesphomeapi import APIClient, ReconnectLogic

from boiler_gateway.config import DeviceSettings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reading:
    object_id: str
    name: str
    value: Any
    unit: str
    updated_at: float  # time.time() when the device last reported a change


@dataclass(frozen=True)
class DeviceSnapshot:
    connected: bool
    readings: dict[str, Reading]
    taken_at: float

    def age(self, object_id: str) -> float | None:
        r = self.readings.get(object_id)
        return None if r is None else self.taken_at - r.updated_at


class Device(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def snapshot(self) -> DeviceSnapshot: ...


def value_of(state: Any) -> Any:
    """The useful value of an ESPHome state message, or None if unknown."""
    if getattr(state, "missing_state", False):
        return None
    for attr in ("state", "current_temperature"):
        if hasattr(state, attr):
            value = getattr(state, attr)
            break
    else:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


class EsphomeDevice:
    """Device backed by aioesphomeapi."""

    def __init__(self, cfg: DeviceSettings):
        self._cfg = cfg
        self._client: APIClient | None = None
        self._reconnect: ReconnectLogic | None = None
        self._entities: dict[int, Any] = {}
        self._readings: dict[str, Reading] = {}
        self._connected = False

    async def start(self) -> None:
        self._client = APIClient(
            self._cfg.esphome_host,
            self._cfg.esphome_port,
            noise_psk=self._cfg.esphome_noise_psk.get_secret_value(),
            client_info="boiler-gateway",
        )
        self._reconnect = ReconnectLogic(
            client=self._client,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            on_connect_error=self._on_connect_error,
        )
        await self._reconnect.start()

    async def stop(self) -> None:
        if self._reconnect is not None:
            await self._reconnect.stop()
        if self._client is not None:
            await self._client.disconnect()
        self._connected = False

    def snapshot(self) -> DeviceSnapshot:
        return DeviceSnapshot(self._connected, dict(self._readings), time.time())

    # Callbacks (also driven directly by tests)

    async def _on_connect(self) -> None:
        assert self._client is not None
        _info, entities, _services = await self._client.device_info_and_list_entities()
        self._entities = {e.key: e for e in entities}
        self._client.subscribe_states(self._on_state)
        self._connected = True
        log.info("connected to device; %d entities", len(self._entities))

    async def _on_disconnect(self, expected: bool) -> None:
        self._connected = False
        if not expected:
            log.warning("device connection lost; reconnecting")

    async def _on_connect_error(self, exc: Exception) -> None:
        self._connected = False
        log.warning("device connection failed: %s", exc.__class__.__name__)

    def _on_state(self, state: Any) -> None:
        entity = self._entities.get(state.key)
        if entity is None:
            return
        self._readings[entity.object_id] = Reading(
            object_id=entity.object_id,
            name=entity.name,
            value=value_of(state),
            unit=getattr(entity, "unit_of_measurement", "") or "",
            updated_at=time.time(),
        )
