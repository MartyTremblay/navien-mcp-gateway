# 0007. A tamper-evident SQLite audit store in the gateway

Status: accepted (2026-10-08)

Principles: applies P5 (every call is accountable), P6 (secrets stay server-side) and P7 (fail safe).

## Context

P5 requires an audit record for every call, including denials, and says audit failure blocks writes. The [data model](../architecture/02-baseline-target.md#main-data-entities) defines what a record holds: request ID, the person (`sub`) and the agent (`client_id`), tool, arguments, policy decision, approval, device result and latency. Records never hold tokens.

The store has to:

- accept a write before any device change happens, so a failed write can stop the change;
- be queryable, for the owner and as evidence for the threat-model tests and any write-up;
- show if records were altered or removed;
- run inside the gateway container (ADR 0006) without another service to operate.

## Options considered

1. **JSON lines in a log file.** Simple and append-only by habit, but not by design. Querying means parsing files, and there is no transaction to confirm a record was written before acting.
2. **SQLite in the gateway container.** A single file, transactional, queryable with SQL, and already part of Python. Writes are durable once committed, so "audit first, then act" can be enforced.
3. **PostgreSQL**, for example Keycloak's. Keycloak's database is in another container and belongs to the identity system. Sharing it would couple audit to identity and give the gateway credentials to a system it should only trust for tokens. A dedicated PostgreSQL would be another service to run for one household.
4. **An OpenTelemetry collector and a log backend** (for example Loki or Elasticsearch). This is the enterprise pattern for operational telemetry, but delivery is asynchronous: the gateway cannot know a record was stored before acting. It suits traces and metrics, not the record of what was authorized.

## Decision

Use SQLite in the gateway container as the audit record of truth (option 2).

- **Append-only by design.** The gateway's code only inserts audit records. It has no update or delete path.
- **Tamper-evident.** Each record stores a SHA-256 hash of its own content plus the previous record's hash, forming a chain. Changing or deleting any record breaks every hash after it. A verification command walks the chain and reports the first break. This detects tampering. It does not prevent it, since someone with write access to the file could rebuild the chain, so off-box copies matter (below).
- **Write ordering for device changes:**
  1. Record the decision (for example `allow`) and commit, before contacting the device. If this commit fails, the call is denied and nothing reaches the device (P5, P7).
  2. Perform the write and the read-back.
  3. Record the outcome (`confirmed`, `unconfirmed` or `failed`) as a second record linked by request ID. If this commit fails, the gateway logs the error loudly and returns the device outcome to the caller with a warning. The change has already happened, so hiding it would be worse.
- **Denials are recorded the same way:** one record, written before the error is returned.
- **SQLite settings:** WAL mode, `synchronous=FULL`, one writer (the gateway process).
- **No secrets.** Records store `sub`, `client_id`, scopes and the token's `jti` for correlation, never the token. Arguments are tool parameters such as setpoints, which hold no personal data.
- **Operational logs are separate.** Structured JSON logs (to the system journal) carry debugging information and follow the same no-secrets rule. They are not the audit record. OpenTelemetry tracing stays a stretch goal and would sit beside the audit store, not replace it.
- **Off-box copies.** The container is included in Proxmox backups. A later increment adds a periodic export of the chain's latest hash to somewhere outside the container, so a rebuilt chain can be detected.
- **Access.** Reading the audit trail is an owner-only capability. Exposing it as an MCP tool needs its own scope (for example `boiler:audit`), decided when that tool is added.

## Consequences

- "Audit first, then act" is enforced by a database transaction rather than by convention.
- Audit evidence for tests and the write-up is a SQL query away.
- The store lives on one container's disk: losing the container without a backup loses the history. Backups are therefore part of the design, not an afterthought.
- Hash chaining detects edits by anyone who doesn't also recompute the chain. Full protection against a privileged attacker needs the off-box hash export.
- Retention is not limited for now: records are small and the household is one. Revisit if the volume grows or personal data is added.
- Moving to an enterprise setting would mean forwarding these records to a central log platform or SIEM. The local store would remain the gateway's own record of what it authorized.
