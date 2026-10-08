# Architecture vision

ADM phase: A. Status: draft.

## Problem

AI agents are becoming useful for operating real systems, but connecting one directly to a system's API gives it all of that API's power, with no record of what it did or why. Enterprises face this with systems of record. This project faces it with a home boiler: a real gas appliance in an occupied house, controlled through an ESPHome device.

## Vision

AI clients can read the boiler's state and change a small set of settings, but only through a gateway that authenticates the client, checks its scopes, applies policy, asks a human when the risk is high, and records everything. The boiler stands in for an enterprise system of record, and the gateway for an enterprise AI control plane.

## Scope

**In scope**
- An MCP server exposing boiler state as resources and a small set of settings as tools.
- Client authentication and per-tool authorization with scopes.
- Write policy: value bounds, rate limits, human approval for high-risk actions.
- Audit of every call, including denials.
- A threat model and tests against it.

**Out of scope**
- Replacing Home Assistant's own ESPHome integration.
- More than one device or household.
- Changes to the device firmware, except to remove a path that bypasses the gateway ([ADR 0001](../adr/0001-remove-device-web-server.md)).

## Stakeholders and concerns

| Stakeholder | Concerns |
|---|---|
| Owner (operator and architect) | Safety, control over what agents can do, a clear audit trail, learning value |
| Household occupants | Heat and hot water stay available and safe; nothing changes unexpectedly |
| Home Assistant (existing system) | Its direct connection and automations keep working |
| AI client (agent) | A clear, stable set of tools; useful errors when a call is denied |
| Service technician | Device settings and error history are not altered without record |
| Readers of the project | Decisions are traceable from principle to working control |

## Target capabilities

1. Read boiler state: temperatures, setpoints, operating mode, burner level, errors.
2. Change space-heating and tank setpoints within gateway bounds, with read-back.
3. Request high-risk actions that wait for human approval.
4. Query the audit trail.

## Constraints

- The device confirms a command 6–9 seconds after it is sent, so writes are slow and must be read back (P2).
- The device is on the local network only.
- One owner builds and runs the system, so every control has to be simple enough to keep working.
- The safety rules in [CLAUDE.md](../../CLAUDE.md) are non-negotiable.

## Assumptions

- The ESPHome native API is reachable from the gateway host and its encryption key is available to the gateway only.
- MCP clients support the transport and auth method chosen in the ADRs.
- Home Assistant and the gateway can both connect to the device at the same time. Verified against the ESPHome documentation: the native API's `max_connections` defaults to 5 on ESP32, and the device's firmware configuration does not override it. Each connection uses RAM, so the gateway should hold one long-lived connection rather than one per request.

## Resolved: a path around the gateway

The gateway governs only the paths that go through it. While checking the assumption above, we found that the device's firmware also ran ESPHome's built-in web server without authentication. Any client on the local network could have reached the device directly and bypassed every control described here.

This is the same problem as a system of record that still accepts direct database connections after an API gateway is put in front of it. It was closed on 2026-10-08 by removing the web server from the firmware ([ADR 0001](../adr/0001-remove-device-web-server.md)), a deliberate exception to the "no firmware changes" scope. Port 80 now refuses connections. The threat model will treat any direct path to the device as part of the attack surface, with a test that keeps port 80 closed.

## Success criteria

- Every call, allowed or denied, has an audit record.
- No write outside the gateway's bounds reaches the device, as shown by tests.
- Every write reports a confirmed, unconfirmed or failed outcome based on read-back.
- No client response or log contains the device key or a client credential.
- Every threat in the threat model has at least one test.
- Home Assistant's integration works unchanged throughout.

## Principles applied

All ten [architecture principles](00-principles.md) apply. The ones that most shape the vision are P1 (least privilege), P4 (humans own high-risk actions), P5 (accountability) and P8 (incremental exposure).

## Next

- Baseline and target architecture (phases B to D).
- ADR 0005: identity provider.
- Hosting: where the gateway runs, and TLS on the local network.
