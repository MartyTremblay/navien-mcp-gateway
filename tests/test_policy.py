from datetime import UTC, datetime, timedelta

import pytest

from boiler_gateway.policy import HOT_WATER_TANK, check_value, missing_scopes, rate_limit_remaining


@pytest.mark.parametrize("value", [40, 40.5, 54, 59.5, 60])
def test_values_inside_bounds_on_a_step(value):
    assert check_value(HOT_WATER_TANK, value) is None


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (39.5, "out_of_bounds"),
        (60.5, "out_of_bounds"),
        (82, "out_of_bounds"),
        (54.25, "not_a_valid_step"),
        (float("nan"), "invalid_value"),
        (float("inf"), "invalid_value"),
        (True, "invalid_value"),
        ("55", "invalid_value"),
    ],
)
def test_values_refused(value, reason):
    assert check_value(HOT_WATER_TANK, value) == reason


def test_rate_limit():
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    assert rate_limit_remaining(HOT_WATER_TANK, None, now) is None
    assert rate_limit_remaining(HOT_WATER_TANK, now - timedelta(seconds=30), now) == timedelta(
        seconds=90
    )
    assert rate_limit_remaining(HOT_WATER_TANK, now - timedelta(minutes=2), now) is None


def test_write_scope_does_not_imply_read_and_vice_versa():
    assert missing_scopes("set_hot_water_tank_setpoint", ["boiler:read"]) == {"boiler:write"}
    assert missing_scopes("get_boiler_status", ["boiler:write"]) == {"boiler:read"}
