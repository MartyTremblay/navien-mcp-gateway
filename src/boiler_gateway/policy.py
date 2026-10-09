"""Per-tool authorization (P1, ADR 0004).

Each tool names the scopes it needs. Scopes don't imply one another:
`boiler:write` does not include `boiler:read`. A tool that isn't listed here
has no scopes that could allow it, so it is denied (P7).
"""

from __future__ import annotations

READ = "boiler:read"
WRITE = "boiler:write"

TOOL_SCOPES: dict[str, frozenset[str]] = {
    "get_boiler_status": frozenset({READ}),
}

# Advertised in Protected Resource Metadata: the minimum for basic use (MCP spec).
SCOPES_SUPPORTED = [READ]


def missing_scopes(tool: str, granted: list[str] | tuple[str, ...]) -> frozenset[str] | None:
    """Scopes the caller lacks for `tool`, or None if the tool is unknown (always denied)."""
    needed = TOOL_SCOPES.get(tool)
    if needed is None:
        return None
    return needed - set(granted)
