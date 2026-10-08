# Architecture principles

ADM phase: Preliminary. Status: draft.

These principles guide every design decision in the gateway. An ADR that departs from one must say so and explain why.

## P1. Least privilege for agents

**Statement:** A client gets only the scopes it needs, per tool. Reading never implies writing.

**Rationale:** AI agents can be steered by their inputs (prompt injection). What an agent can do should be limited by what it is allowed to do, not by what it decides to do.

**Implications:** Scopes such as `boiler:read` and `boiler:write` are checked on every call. Tools are narrow (one setting each), not general "set any entity" tools.

## P2. The device is the source of truth

**Statement:** A write is successful only when the device reports the new value.

**Rationale:** The boiler confirms a command several seconds after it is sent, and a command can be lost. Reporting success on send would mislead the caller and the audit trail.

**Implications:** Every write tool reads back and returns `confirmed`, `unconfirmed` or `failed`. The audit record stores the confirmed outcome, not the intent.

## P3. Controls independent of the device

**Statement:** The gateway enforces its own limits, stricter than the device's, whatever the device would accept.

**Rationale:** Defence in depth. Firmware limits can change, and the gateway is the only place that knows who is asking and why.

**Implications:** Value bounds, rate limits and allowed tools are gateway policy, under version control. Space heating is bounded to 40–70 °C and the hot-water tank to 40–60 °C, inside the device's 40–82 °C range.

## P4. Humans own high-risk actions

**Statement:** Actions that could cause harm or are hard to reverse need explicit human approval before they reach the device.

**Rationale:** This is a gas appliance in an occupied house. Automation should handle routine changes, not consequential ones.

**Implications:** Power, recirculation and similar actions go through an approval step. Approval is recorded with who approved it and when. No approval within the timeout means no action.

## P5. Every call is accountable

**Statement:** Every call is audited: who, which tool, arguments, policy decision, result and latency. That includes calls that were denied.

**Rationale:** Denied calls are often the most useful evidence, for example of an injection attempt or a misconfigured client.

**Implications:** Audit records are structured and queryable. The audit path cannot be skipped, and audit failure blocks writes.

## P6. Secrets stay server-side

**Statement:** Device credentials never leave the gateway, and client credentials are never logged.

**Rationale:** An agent cannot leak what it never sees. Clients are the least trusted part of the system.

**Implications:** Secrets come from the environment or a secret store, never from code or tool output. Logs and audit records redact credentials.

## P7. Fail safe

**Statement:** When the gateway is unsure, it denies rather than allows.

**Rationale:** For a physical device, a missed change is cheap and a wrong change can be expensive.

**Implications:** An unreachable device, a policy error, an expired approval or an unknown client all result in denial. Writes are never retried automatically.

## P8. Expose capability incrementally

**Statement:** Start read-only, and add write capability one tool at a time, each with bounds and tests.

**Rationale:** Each new capability widens the attack surface. Adding them one at a time keeps each step reviewable and reversible.

**Implications:** The roadmap is a sequence of increments, each ending with a compliance check (ADM phase G).

## P9. Do not disrupt existing systems

**Statement:** The gateway is a second, governed path. Home Assistant's existing direct connection keeps working unchanged.

**Rationale:** Governance should be added without breaking what already runs, as it would be in an enterprise.

**Implications:** No changes to the device firmware or Home Assistant configuration are required for the gateway to work.

## P10. Enterprise pattern by default, simplification by decision

**Statement:** Prefer the pattern an enterprise would use. Where a simpler option is chosen, record the trade-off in an ADR.

**Rationale:** The project exists to practise enterprise AI architecture, so the reasoning matters as much as the result.

**Implications:** Interim shortcuts, such as static tokens before OAuth, are allowed, but each one has an ADR stating when and how it will be replaced.
