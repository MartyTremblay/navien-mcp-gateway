# Compliance check: increment 1 (read-only gateway)

ADM phase G. Date: 2026-10-09. Deployed commit: `77f7b31`. Tests: 57 passing.

The six checks are defined in the [roadmap](../architecture/03-roadmap.md#implementation-governance-phase-g). Result: **passed**, with open items carried forward. (Home Assistant's continued operation, P9, was confirmed by the owner on 2026-10-09.)

## 1. Principles

| Principle | How increment 1 applies it | Result |
|---|---|---|
| P1 Least privilege for agents | One read-only tool; `boiler:read` checked per tool; the agent's client gets only the scopes the owner approves on a consent screen; tokens carry no name, email or roles | Pass |
| P2 The device is the source of truth | Status comes only from the device's own reports; `stale` when disconnected; `last_reported` and `device_connected_since` so a reconnect isn't read as a change | Pass (writes and read-back start in increment 2) |
| P3 Controls independent of the device | Authentication, scopes and audit happen in the gateway; the device's web server was removed so the gateway can't be bypassed that way (ADR 0001) | Pass (value bounds start in increment 2) |
| P4 Humans own high-risk actions | No high-risk tool is exposed; the owner signs in and approves each agent's access | Pass (approvals in increment 4) |
| P5 Every call is accountable | Every MCP request is audited, including refusals: no token, invalid token with its reason, missing scope, unknown tool. Tool calls get a decision and an outcome. Chain verified | Pass |
| P6 Secrets stay server-side | Device key only in the gateway's root-only environment file; tokens never logged or audited (only `jti`); clients never see the device key | Pass, with two incidents (see check 6) |
| P7 Fail safe | No signing keys, no access; audit failure refuses the request (503); unknown tools denied; device commands don't exist in this increment | Pass |
| P8 Expose capability incrementally | Read-only first, one tool | Pass |
| P9 Do not disrupt existing systems | The gateway is a second connection to the device; Home Assistant keeps its own | Pass: Home Assistant confirmed still connected to the controller after the address change (owner check, 2026-10-09) |
| P10 Enterprise pattern by default | Separate identity provider, resource-server-only gateway, audience-bound tokens, segmented lab network, per-environment reverse proxy, tamper-evident audit; simplifications recorded in ADRs | Pass |

## 2. Decisions recorded

ADRs [0001](../adr/0001-remove-device-web-server.md) to [0007](../adr/0007-audit-store.md) are accepted. Decisions made during the increment were recorded as ADR updates:

- ADR 0003: earlier-revision MCP clients are served statelessly; the first real client uses 2026-07-28.
- ADR 0005: the first real client doesn't send the RFC 8707 `resource` parameter; the documented fallback was applied to that client only; `offline_access` mitigated by refresh token rotation and a maximum offline session.
- ADR 0006 (amended twice): lab VLAN with router rules instead of the Proxmox firewall; dedicated lab reverse proxy.

Smaller operational fixes (no `.env` file read in production; bounded graceful shutdown) are in commit messages; they don't change the architecture.

## 3. Exit criteria and evidence

| Exit criterion | Evidence | Result |
|---|---|---|
| A real MCP client connects through the full sign-in and reads the status | Claude Code signed in (consent, OTP), called `get_boiler_status`, and reported live values; audit records `allow` and `outcome ok` for `claude-code` | Pass |
| Tokens without `boiler:read`, expired, or for another audience are refused, and each refusal is audited | Unit and HTTP tests (`test_auth`, `test_server`); live: Claude Code's first token was refused as `invalid_token:wrong_audience` and audited | Pass |
| The audit verification command reports an intact chain | `verify` on the deployed store: 52 records, chain intact | Pass |
| Home Assistant still works unchanged | Owner confirmed Home Assistant still connects to the controller | Pass |

## 4. Threat model

[Version 1](../threat-model.md) covers 22 threats with controls and evidence, updated during deployment (T2 live evidence, T12 incident and fix). Open or partly mitigated:

- **T17 accepted** (owner decision, 2026-10-09): any device on the household network can try the controller's API port and use up its connection slots. The impact is availability, not control; a router rule was considered and not adopted.
- **T14 partial**: audit truncation needs an off-box anchor (increment 5).
- **T16 partial**: Home Assistant holds the device key by design.
- **T21 partial**: installs are version-pinned, not hash-pinned.

## 5. Restore

Increment 1 is read-only and changed no boiler setting. Infrastructure changes made for it, all deliberate and recorded:

- The device's web server was removed from its firmware (ADR 0001).
- The controller was given a fixed address (it had been on a dynamic one).
- No Proxmox firewall setting was left changed; the lab is enforced by the router.

## 6. Secrets

- Repository: full history scanned for addresses, hostnames and the values below; none found. Commit author emails were rewritten to a no-reply address before the repository went public.
- Device key: only in the gateway's root-only environment file and the developer's local `.env` (gitignored).
- Incidents: a Keycloak client secret and a DNS API token were pasted into a chat while debugging; both were rotated immediately. A community install script's default admin password was removed before use.

## Carried forward

- Narrow the gateway's allowed `Host` values to the one the reverse proxy actually forwards.
- Test whether the lab reverse proxy buffers streamed responses (ADR 0006); the long-lived `subscriptions/listen` stream works, but buffering hasn't been measured.
- Make the lab and household reverse proxy admin pages visibly different (an operator error during deployment came from their being identical).
- Increment 2 starts with the hot-water tank setpoint (roadmap).
