import math
from dataclasses import dataclass

import pytest

from boiler_gateway.config import DeviceSettings
from boiler_gateway.device import EsphomeDevice, value_of


@dataclass
class Entity:
    key: int
    object_id: str
    name: str
    unit_of_measurement: str = ""


@dataclass
class SensorState:
    key: int
    state: object
    missing_state: bool = False


@dataclass
class ClimateState:
    key: int
    current_temperature: float


class FakeClient:
    def __init__(self, entities):
        self.entities = entities
        self.on_state = None
        self.commands = []  # anything that would change the device

    async def device_info_and_list_entities(self):
        return object(), self.entities, []

    def subscribe_states(self, cb):
        self.on_state = cb

    def __getattr__(self, name):
        # Any command-style call is recorded so the test can prove none happen.
        def record(*args, **kwargs):
            self.commands.append(name)

        return record


ENTITIES = [
    Entity(1, "navien_outlet_temp", "Navien Outlet Temp", "°C"),
    Entity(2, "navien_operating_state", "Navien Operating State"),
    Entity(3, "navien_outdoor_temp", "Navien Outdoor Temp", "°C"),
    Entity(4, "navien_dhw_set_temperature", "Navien DHW Set Temperature"),
]


@pytest.fixture
async def device():
    cfg = DeviceSettings(_env_file=None, esphome_host="192.0.2.10", esphome_noise_psk="dGVzdA==")
    dev = EsphomeDevice(cfg)
    dev._client = FakeClient(ENTITIES)
    await dev._on_connect()
    return dev


def test_value_of():
    assert value_of(SensorState(1, 51.0)) == 51.0
    assert value_of(SensorState(1, 51.0, missing_state=True)) is None
    assert value_of(SensorState(1, math.nan)) is None
    assert value_of(ClimateState(1, 51.0)) == 51.0
    assert value_of(object()) is None


async def test_states_are_cached_with_names_and_units(device):
    device._client.on_state(SensorState(1, 51.0))
    device._client.on_state(SensorState(2, "Standby"))
    snap = device.snapshot()
    assert snap.connected
    assert snap.readings["navien_outlet_temp"].value == 51.0
    assert snap.readings["navien_outlet_temp"].unit == "°C"
    assert snap.readings["navien_operating_state"].value == "Standby"
    assert snap.age("navien_outlet_temp") >= 0


async def test_unknown_values_are_none_not_nan(device):
    device._client.on_state(SensorState(3, math.nan))
    assert device.snapshot().readings["navien_outdoor_temp"].value is None


async def test_states_for_unknown_entities_are_ignored(device):
    device._client.on_state(SensorState(99, 1.0))
    assert device.snapshot().readings == {}


async def test_connected_since_is_reported_and_cleared(device):
    assert device.snapshot().connected_since is not None
    await device._on_disconnect(expected=False)
    assert device.snapshot().connected_since is None


async def test_disconnect_is_visible(device):
    await device._on_disconnect(expected=False)
    assert not device.snapshot().connected
    await device._on_connect_error(OSError())
    assert not device.snapshot().connected


async def test_reading_never_sends_commands(device):
    device._client.on_state(SensorState(1, 51.0))
    device.snapshot()
    assert device._client.commands == []
