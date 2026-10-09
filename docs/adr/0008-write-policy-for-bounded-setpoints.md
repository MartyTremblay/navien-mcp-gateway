# 0008. Write policy for bounded setpoints

Status: accepted (2026-10-09)

Principles: applies P1 (least privilege), P2 (the device is the source of truth), P3 (controls independent of the device), P5 (accountability), P7 (fail safe) and P8 (incremental exposure).

## Context

Increment 2 adds the first tool that changes the boiler: the hot-water tank setpoint ([roadmap](../architecture/03-roadmap.md)). The device exposes it as an ESPHome number entity accepting 40 to 82 °C in 0.5 °C steps. The command is fire and forget: the library sends it and returns, with no acknowledgement. The boiler confirms a change by reporting the new value a few seconds later (6 to 9 seconds observed by the owner).

The write tool is reachable by an AI agent, which may be steered by prompt injection (threat model T10). The controls must hold even if the agent asks for the worst allowed thing, repeatedly.

## Decision

**Authorization**

- The tool requires `boiler:write`. Scopes don't imply each other (ADR 0004), so a write token also needs `boiler:read` to reach the server at all.
- A token without `boiler:write` gets a 403 `insufficient_scope` challenge naming `boiler:write`, so the client can run a step-up sign-in and the owner approves the new permission explicitly.

**Bounds (gateway policy, independent of the device)**

- 40 to 60 °C, in 0.5 °C steps. Anything else is refused before the device is contacted.

**Rate limit**

- One write per tool every 2 minutes, across all clients. It protects the device, not fairness between agents.
- The rate limit is derived from the audit trail: the time of the last write attempt the policy allowed for that tool. It survives restarts and has one source of truth. A failed or unconfirmed write still counts.
- Setting the value the boiler already reports sends no command, is reported as `confirmed` with no change, is audited, and does not count against the limit.

**Order of operations**

1. Scope, bounds and rate limit checked; refusals audited with their reason.
2. The device must be connected; otherwise the write is refused (P7).
3. The policy decision is committed to the audit store before the command is sent. If it can't be recorded, nothing is sent (ADR 0007).
4. The command is sent once. It is never retried automatically.
5. Read-back: the gateway waits up to 20 seconds for the boiler's own reported setpoint (the sensor, not the number entity's echo) to equal the requested value.
6. The outcome is recorded: `confirmed`, `unconfirmed` (no report of the new value within the timeout) or `failed` (the command could not be sent), with the value before and the value reported after.
7. Writes are serialized: a second write waits for the first to finish.

**Containment in the device adapter**

- The adapter's command method refuses any entity not on an explicit allow-list. In this increment the list holds only the hot-water tank setpoint. A bug elsewhere can't become a command to a switch or button.

**Kill switch**

- `GATEWAY_WRITES_ENABLED`, off by default. While off, the write tool is not registered, so agents don't see it at all. The deployed gateway stays read-only until the owner turns writes on deliberately.
- No live write while a known device fault is under investigation (roadmap). Live testing happens with the owner present, and the original value is restored afterwards.

## Consequences

- An agent that is tricked into writing can, at worst, set the tank between 40 and 60 °C once every 2 minutes, and every attempt is audited with the person and the agent.
- `unconfirmed` is an honest answer, not an error: the gateway doesn't know whether the boiler accepted the change. The agent and the owner see that distinction.
- Deriving the rate limit from the audit trail makes the audit store part of the write path's availability. That's consistent with ADR 0007 (audit failure already blocks writes).
- The 20-second read-back means a write call can take that long. MCP tool calls tolerate it; the result says how long confirmation took.
- Bounds, rate limits and the allow-list are code constants in this increment. Increment 3 moves them into versioned configuration when a second write tool arrives.
