# Compliance check: increment 2 (first bounded write)

ADM phase G. Date: 2026-10-13. Deployed commit: `acce467`, with writes off. Tests: 101 passing.

The six checks are defined in the [roadmap](../architecture/03-roadmap.md#implementation-governance-phase-g). Result: **passed**, with two fixes still to be exercised in a live write, and open items carried forward.

The live write ran on commit `87b6cf0`. It found four defects, fixed in `7ea0df0`, `f5b3f64`, `a6b336b` and `acce467`. Of those, the change to refused-call records was verified live (audit record 241). The whole-degree step and the `scope_ok` label are covered by tests but haven't yet run in a live write, because writes stay off between test sessions.

Numbers in brackets are audit record sequence numbers from the deployed store.

## 1. Principles

| Principle | How increment 2 applies it | Result |
|---|---|---|
| P1 Least privilege for agents | `boiler:write` is a separate scope, never requested by default; the owner approves it on the consent screen. The client couldn't step up, so write access was granted for one session and revoked afterwards ([ADR 0004 update](../adr/0004-oauth-2-1-resource-server.md#update-2026-10-13-step-up-isnt-supported-by-the-client-in-use)) | Pass, with an accepted trade-off |
| P2 The device is the source of truth | A write counts only when the boiler reports the new value. Live: 54.5 °C was sent and never reported, and the result was `unconfirmed`, not success [209] | Pass |
| P3 Controls independent of the device | Bounds 40–60 °C in the gateway, not the device's 40–82 °C. Live: 65 °C refused before the device was contacted [218]. The step now follows what the boiler applies (whole degrees), not what the entity accepts ([ADR 0008](../adr/0008-write-policy-for-bounded-setpoints.md)) | Pass |
| P4 Humans own high-risk actions | No high-risk tool exists; the adapter refuses any entity not on its allow-list. The owner turned writes on, watched the session, and turned them off | Pass (approvals in increment 4) |
| P5 Every call is accountable | Each write has a scope decision, a policy decision committed before the command, and an outcome. Every refusal is recorded with its reason, and now with the requested value [241]. Chain verified twice | Pass |
| P6 Secrets stay server-side | No tokens in the audit store (scopes and `jti` only); credential-like argument names are never recorded | Pass |
| P7 Fail safe | No automatic retry: the unconfirmed write was checked, not repeated. Kill switch off by default and between sessions. Audit failure means no command (tested) | Pass |
| P8 Expose capability incrementally | One write tool, one entity, narrowest range | Pass |
| P9 Do not disrupt existing systems | Home Assistant kept its own connection and showed the restored setpoint, 54.00 °C (owner check) | Pass |
| P10 Enterprise pattern by default | Audit before act, read-back, rate limit from the audit trail, kill switch, time-boxed privilege with revocation at the identity provider | Pass |

## 2. Decisions recorded

- [ADR 0008](../adr/0008-write-policy-for-bounded-setpoints.md), the write policy: accepted before the increment, and amended after the live write (whole degrees).
- [ADR 0007](../adr/0007-audit-store.md), the audit store: refused calls record the requested arguments, with guards for an unvalidated body; the two decision records per write call are explained.
- [ADR 0004](../adr/0004-oauth-2-1-resource-server.md), authorization: update for a client that can't step up (pinned scope for a session, then revoked).

Smaller fixes that don't change the architecture are in commit messages: server instructions that follow the kill switch, and the `scope_ok` label.

## 3. Exit criteria and evidence

| Exit criterion | Evidence | Result |
|---|---|---|
| Out-of-range values, rate-limited calls and calls without `boiler:write` are refused and audited, and nothing reaches the device | Tests (`test_writes`, `test_policy`). Live: out of bounds [218]; rate limited, "Try again in 15 seconds" [222]; missing scope [180, 190, 241]. No outcome record follows any of them, so no command was sent; the boiler's setpoint was unchanged after each | Pass |
| An in-range write is confirmed by read-back | Live: 55 °C confirmed in 5.2 s [214–216]; 54 °C confirmed in 5.4 s [223–225] | Pass |
| Every value changed during testing is restored, and the restore is recorded | 55 → 54 °C, confirmed [225]; gateway status and Home Assistant both showed 54 °C afterwards | Pass |
| No write testing while a known device fault is under investigation | The boiler's recurring fault was repaired before the session; no active error before, during or after (error count unchanged) | Pass |

Audit chain: `verify` reported "chain intact" from the pre-test anchor (227 records), and again after the redeploy (241 records).

## 4. Threat model

[Version 2](../threat-model.md) adds T23–T30 for writes, all with tests; the live write added evidence for T23, T24, T25 and T29.

- **T29 accepted trade-off:** the client doesn't step up, so consent happens at sign-in for a time-boxed session (ADR 0004 update).
- Two lessons added: the device's advertised range wasn't its behaviour, and a control that depends on the client.
- Carried from increment 1, unchanged: T17 accepted; T14, T16 and T21 partial.

## 5. Restore

- Hot-water tank setpoint: 54 °C before, 54 °C after (gateway read-back and Home Assistant).
- Writes turned off again after the session (the kill switch).
- Client write access revoked: pinned scope removed, re-authenticated read-only, the client's sessions ended at the identity provider. Afterwards, a write attempt was refused for missing scope [241].
- No other device setting was changed. The only other command, 54.5 °C, wasn't applied by the boiler.

## 6. Secrets

- Repository: all 48 commits scanned for addresses, hostnames, personal email and key material; none found.
- Audit store: no tokens. Refused calls record arguments only when no argument name looks like a credential.
- No secrets were pasted into chat during the live-write session.

## Carried forward

- In the next live write session: confirm the whole-degree refusal (54.5 °C refused before sending) and the `scope_ok` label in the audit trail.
- Step-up: revisit the pinned-scope workaround when the client supports step-up.
- Status tool: add the outdoor temperature (a sensor was installed during the boiler repair). Check whether outdoor reset is active before increment 3, since the roadmap expects it can override the space-heating setpoint.
- From increment 1, still open: narrow the allowed `Host` values; measure reverse proxy buffering; make the two reverse proxy admin pages visibly different.
