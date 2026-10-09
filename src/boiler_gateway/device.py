"""Device adapter: the only code that talks to the boiler's controller (ADR 0002).

One long-lived, Noise-encrypted connection to the ESPHome native API, kept up
by the library's reconnect logic. The adapter caches every state update with
the time it arrived, so readers can tell fresh values from stale ones (P2).

ESPHome sends a state when it changes, and a full set on (re)connect. A
value's age therefore grows while it stays the same: an old value is still
current as long as the connection is up. Readers treat "not connected" as
stale, not "old". `updated_at` is when the value was last *reported*: after a
reconnect every value is re-sent, so a recent `updated_at` close to
`connected_since` doesn't mean the value changed.

The `Device` protocol is the seam for a later split into a separate service
(ADR 0002, option 3).

Commands (ADR 0008): `set_number` is the only method that changes the device,
and it refuses any entity not in `WRITABLE`. ESPHome commands are fire and
forget, so callers confirm a change with `wait_for_value`, which watches what
the boiler reports rather than trusting that the command arrived.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol

from aioesphomeapi import APIClient, ReconnectLogic

from boiler_gateway.config import DeviceSettings

log = logging.getLogger(__name__)

# The only entities the gateway may command (ADR 0008). Everything else on the
# device (main power, recirculation, hot button, restart, ...) is unreachable.
WRITABLE: frozenset[str] = frozenset({"navien_dhw_setpoint"})


class CommandRefused(Exception):
    """The adapter refused to send a command (not allowed, unknown or not connected)."""


@dataclass(frozen=True)
class Reading:
    object_id: str
    name: str
    value: Any
    unit: str
    updated_at: float  # time.time() when the device last reported this value


@dataclass(frozen=True)
class DeviceSnapshot:
    connected: bool
    readings: dict[str, Reading]
    taken_at: float
    connected_since: float | None = None  # when the current connection was made

    def age(self, object_id: str) -> float | None:
        r = self.readings.get(object_id)
        return None if r is None else self.taken_at - r.updated_at


class Device(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def snapshot(self) -> DeviceSnapshot: ...
    def set_number(self, object_id: str, value: float) -> None: ...
    async def wait_for_value(
        self, object_id: str, expected: Any, timeout: float, tolerance: float = 0.01
    ) -> Reading | None: ...


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
        self._connected_since: float | None = None
        self._changed = asyncio.Condition()

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
        return DeviceSnapshot(
            self._connected,
            dict(self._readings),
            time.time(),
            self._connected_since if self._connected else None,
        )

    # Callbacks (also driven directly by tests)

    async def _on_connect(self) -> None:
        assert self._client is not None
        _info, entities, _services = await self._client.device_info_and_list_entities()
        self._entities = {e.key: e for e in entities}
        self._client.subscribe_states(self._on_state)
        self._connected = True
        self._connected_since = time.time()
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
        asyncio.get_running_loop().create_task(self._notify())

    async def _notify(self) -> None:
        async with self._changed:
            self._changed.notify_all()

    # Commands (ADR 0008)

    def set_number(self, object_id: str, value: float) -> None:
        """Send one number command. Refuses anything not in WRITABLE. Never retries."""
        if object_id not in WRITABLE:
            raise CommandRefused(f"{object_id} is not writable")
        if not self._connected or self._client is None:
            raise CommandRefused("device not connected")
        entity = next((e for e in self._entities.values() if e.object_id == object_id), None)
        if entity is None:
            raise CommandRefused(f"{object_id} not found on device")
        self._client.number_command(entity.key, float(value), getattr(entity, "device_id", 0) or 0)
        log.info("command sent: %s = %s", object_id, value)

    async def wait_for_value(
        self, object_id: str, expected: Any, timeout: float, tolerance: float = 0.01
    ) -> Reading | None:
        """Wait until the device reports `expected` for `object_id`; None on timeout."""

        def matches() -> Reading | None:
            r = self._readings.get(object_id)
            if r is None or r.value is None:
                return None
            try:
                return r if abs(float(r.value) - float(expected)) <= tolerance else None
            except (TypeError, ValueError):
                return r if r.value == expected else None

        try:
            async with asyncio.timeout(timeout):
                async with self._changed:
                    while (hit := matches()) is None:
                        await self._changed.wait()
                    return hit
        except TimeoutError:
            return None
