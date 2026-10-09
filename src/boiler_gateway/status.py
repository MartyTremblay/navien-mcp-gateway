"""The read-only boiler status shown to agents.

Only a curated set of values is exposed. Diagnostic entities (raw unknown
bytes, IP and MAC addresses, firmware details) are left out: an agent doesn't
need them, and less exposure means less to leak or misuse (P1).

Values are what the device last reported. When the gateway isn't connected to
the device, every value is marked stale rather than presented as current (P2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from boiler_gateway.device import DeviceSnapshot

# (field shown to agents, ESPHome object_id)
FIELDS: tuple[tuple[str, str], ...] = (
    ("operating_state", "navien_operating_state"),
    ("heating_mode", "navien_heating_mode"),
    ("boiler_active", "navien_boiler_active"),
    ("burner_level_percent", "navien_heat_capacity"),
    ("tank_temperature_c", "navien_outlet_temp"),
    ("hot_water_tank_setpoint_c", "navien_dhw_set_temp"),
    ("space_heating_supply_c", "navien_sh_outlet_temp"),
    ("space_heating_return_c", "navien_sh_return_temp"),
    ("space_heating_setpoint_c", "navien_sh_set_temp"),
    ("error_code", "navien_error_code"),
    ("error_level", "navien_error_level"),
    ("error_count", "navien_error_count"),
    ("controller_link_ok", "navien_connection_status"),
)

_INTEGER_FIELDS = {"error_code", "error_level", "error_count", "burner_level_percent"}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def build_status(snapshot: DeviceSnapshot) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field, object_id in FIELDS:
        reading = snapshot.readings.get(object_id)
        if reading is None:
            values[field] = None
            continue
        value = reading.value
        if field in _INTEGER_FIELDS and isinstance(value, float):
            value = round(value)
        values[field] = {"value": value, "last_changed": _iso(reading.updated_at)}
    return {
        "device_connected": snapshot.connected,
        "stale": not snapshot.connected,
        "as_of": _iso(snapshot.taken_at),
        "values": values,
        "note": (
            "Values are the device's last reports. The device reports changes, so an old "
            "last_changed is normal while device_connected is true."
        ),
    }
