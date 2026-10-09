"""Per-tool authorization (P1, ADR 0004).

Each tool names the scopes it needs. Scopes don't imply one another:
`boiler:write` does not include `boiler:read`. A tool that isn't listed here
has no scopes that could allow it, so it is denied (P7).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

READ = "boiler:read"
WRITE = "boiler:write"

TOOL_SCOPES: dict[str, frozenset[str]] = {
    "get_boiler_status": frozenset({READ}),
    "set_hot_water_tank_setpoint": frozenset({WRITE}),
}

# Advertised in Protected Resource Metadata: the minimum for basic use (MCP spec).
SCOPES_SUPPORTED = [READ]


def missing_scopes(tool: str, granted: list[str] | tuple[str, ...]) -> frozenset[str] | None:
    """Scopes the caller lacks for `tool`, or None if the tool is unknown (always denied)."""
    needed = TOOL_SCOPES.get(tool)
    if needed is None:
        return None
    return needed - set(granted)


@dataclass(frozen=True)
class SetpointRule:
    """Gateway-side limits for one writable setpoint (ADR 0008), independent of the device."""

    tool: str
    command_entity: str  # what the command goes to
    reported_entity: str  # what the boiler reports back (read-back source)
    minimum: float
    maximum: float
    step: float
    min_interval: timedelta


HOT_WATER_TANK = SetpointRule(
    tool="set_hot_water_tank_setpoint",
    command_entity="navien_dhw_setpoint",
    reported_entity="navien_dhw_set_temp",
    minimum=40.0,
    maximum=60.0,
    step=0.5,
    min_interval=timedelta(minutes=2),
)

READ_BACK_TIMEOUT_SECONDS = 20.0


def check_value(rule: SetpointRule, value: float) -> str | None:
    """None if `value` is allowed, else the refusal reason."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "invalid_value"
    if value < rule.minimum or value > rule.maximum:
        return "out_of_bounds"
    if abs(value / rule.step - round(value / rule.step)) > 1e-9:
        return "not_a_valid_step"
    return None


def rate_limit_remaining(
    rule: SetpointRule, last_attempt: datetime | None, now: datetime | None = None
) -> timedelta | None:
    """Time still to wait before another write, or None if a write is allowed now."""
    if last_attempt is None:
        return None
    now = now or datetime.now(UTC)
    wait = last_attempt + rule.min_interval - now
    return wait if wait > timedelta(0) else None
