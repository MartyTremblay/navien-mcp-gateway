# Baseline and target architecture

ADM phases: B (Business), C (Data and Application) and D (Technology), combined. Status: draft.

This document describes the system as it is (baseline) and as it will be (target), and lists the gaps between them. It builds on the [principles](00-principles.md), the [vision](01-vision.md) and ADRs [0001](../adr/0001-remove-device-web-server.md) to [0006](../adr/0006-hosting-and-tls.md). Hostnames are written as `lab.<domain>`.

## Baseline

Today, Home Assistant is the only system that talks to the boiler's controller. The controller's unauthenticated web server was removed in ADR 0001, so the native API is the only network path to the device.

```mermaid
flowchart LR
    household(["Household members"])
    owner(["Owner"])
    nabu["Nabu Casa<br/>(remote access)"]
    ha["Home Assistant"]
    esp["ESPHome controller<br/>(ESP32 on RS485)"]
    boiler[("Navien boiler")]

    household -- app / browser --> nabu
    owner -- app / browser --> nabu
    nabu --> ha
    ha -- "native API, Noise-encrypted<br/>(port 6053)" --> esp
    esp -- "NaviLink RS485" --> boiler
```

Baseline characteristics:

- One client of the device (Home Assistant), holding the device's encryption key.
- No AI access. No audit of who changed a setting, other than Home Assistant's own history.
- Device-side limits only: the firmware accepts setpoints from 40 to 82 °C.

## Target

The gateway adds a second, governed path for AI clients. Home Assistant's path is unchanged (P9).

```mermaid
flowchart LR
    owner(["Owner<br/>(resource owner, approver)"])
    agent(["AI client<br/>(MCP client)"])
    kc["Keycloak<br/>(authorization server)"]
    gw["MCP gateway<br/>(resource server)"]
    esp["ESPHome controller"]
    boiler[("Navien boiler")]
    ha["Home Assistant<br/>(unchanged)"]
    audit[("Audit store")]

    owner -- "signs in, grants scopes" --> kc
    kc -- "access token (aud = gateway)" --> agent
    agent -- "MCP over HTTPS + bearer token" --> gw
    gw -- "validate token (JWKS)" --> kc
    gw -- "approval request" --> owner
    gw -- "native API, Noise-encrypted" --> esp
    gw --> audit
    ha -- "native API, Noise-encrypted" --> esp
    esp --> boiler
```

## Phase B: Business architecture

Kept deliberately thin: one household, one device.

### Actors and roles

| Actor | Role in the target |
|---|---|
| Owner | Resource owner: grants scopes to AI clients in Keycloak, approves high-risk actions, reviews the audit trail |
| AI client | Acts for the owner within granted scopes. Cannot approve its own high-risk requests |
| Household members | Use heat and hot water. Affected by changes; do not use the gateway |
| Home Assistant | Existing automation and UI. Keeps its own direct path |
| Service technician | Needs device settings and error history to be explainable from records |

### Business services

| Service | Scope needed | Policy |
|---|---|---|
| Read boiler state | `boiler:read` | Always allowed with a valid token |
| Change space-heating setpoint | `boiler:write` | Gateway bounds 40–70 °C, rate limit, read-back |
| Change hot-water tank setpoint | `boiler:write` | Gateway bounds 40–60 °C, rate limit, read-back |
| High-risk actions (power, recirculation, hot button) | `boiler:write` | Human approval before reaching the device (P4) |
| Review audit trail | Owner only | Read-only |

## Phase C: Data architecture

### Main data entities

```mermaid
erDiagram
    TOKEN_CONTEXT ||--o{ TOOL_CALL : authorizes
    TOOL_CALL ||--|| POLICY_DECISION : gets
    TOOL_CALL |o--o| APPROVAL : "may need"
    TOOL_CALL |o--o| DEVICE_WRITE : "may cause"
    DEVICE_WRITE ||--|| READ_BACK : "confirmed by"
    TOOL_CALL ||--|| AUDIT_RECORD : "recorded as"

    TOKEN_CONTEXT {
        string sub "person who granted access"
        string client_id "agent acting for them"
        string scope
        string aud "must equal the gateway"
        datetime exp
    }
    TOOL_CALL {
        string request_id
        string tool
        json arguments
        datetime received_at
    }
    POLICY_DECISION {
        string outcome "allow, deny, needs_approval"
        string reason "e.g. out_of_bounds, rate_limited"
    }
    APPROVAL {
        string approver
        string outcome "approved, rejected, expired"
        datetime decided_at
    }
    DEVICE_WRITE {
        string entity
        float requested_value
    }
    READ_BACK {
        string outcome "confirmed, unconfirmed, failed"
        float reported_value
        int wait_ms
    }
    AUDIT_RECORD {
        string request_id
        string sub
        string client_id
        string tool
        json arguments
        string decision
        string result
        int latency_ms
    }
```

### Data classification

| Data | Class | Where it lives | Rule |
|---|---|---|---|
| Device encryption key | Secret | Gateway container only (environment or secret store) | Never logged or returned (P6) |
| Access tokens | Secret, short-lived (5 min) | In transit only | Never logged; never passed on (ADR 0004) |
| Keycloak signing keys, admin credentials | Secret | Keycloak container | Not reachable from the gateway |
| Audit records | Internal | SQLite in the gateway container (ADR 0007) | Hold `sub` and `client_id`, never tokens. Audit failure blocks writes (P5) |
| Boiler telemetry | Internal | Read live from the device | Not persisted by the gateway beyond audit context |

## Phase C: Application architecture

### Gateway components

Every request passes through the same pipeline. No tool handler can be reached without passing authentication, authorization and policy, and every outcome, including denials, is written to the audit store.

```mermaid
flowchart TB
    req["HTTPS request<br/>(from Zoraxy)"] --> transport
    subgraph gateway["MCP gateway (one process)"]
        transport["Transport<br/>Streamable HTTP, Origin and<br/>header-body validation"]
        authn["Authentication<br/>token signature, expiry,<br/>issuer, audience"]
        authz["Authorization<br/>per-tool scope check"]
        policy["Policy<br/>bounds, rate limits,<br/>risk classification"]
        approval["Approval<br/>(mechanism pending)"]
        tools["Tool handlers<br/>read state, set setpoints"]
        adapter["Device adapter<br/>aioesphomeapi, one long-lived<br/>connection, read-back"]
        auditw["Audit writer"]

        transport --> authn --> authz --> policy
        policy -- "allow" --> tools
        policy -- "needs approval" --> approval --> tools
        tools --> adapter
        transport -. "every outcome" .-> auditw
        authn -.-> auditw
        authz -.-> auditw
        policy -.-> auditw
        tools -.-> auditw
    end
    adapter --> device["ESPHome controller"]
    auditw --> store[("Audit store")]
```

The device adapter sits behind its own interface so it can later become a separate service (ADR 0002, option 3).

### A setpoint change, end to end

```mermaid
sequenceDiagram
    autonumber
    participant C as AI client
    participant Z as Zoraxy (TLS)
    participant G as Gateway
    participant K as Keycloak
    participant D as ESPHome controller
    participant A as Audit store

    C->>Z: POST /mcp tools/call set_sh_setpoint(55)<br/>Authorization: Bearer token
    Z->>G: forward (bridge, HTTP)
    G->>G: validate Origin and headers
    G->>K: fetch signing keys (cached)
    G->>G: verify token: signature, exp, iss, aud
    G->>G: scope boiler:write? bounds 40-70? rate limit ok?
    G->>D: set SH setpoint = 55
    D-->>G: state update (6-9 s later): 55
    G->>A: audit: sub, client_id, tool, args, allow, confirmed, latency
    G-->>C: result: confirmed, 55 °C
```

If any check fails, the gateway stops at that step, writes an audit record with the reason, and returns the matching error: 401 for a missing or invalid token, 403 `insufficient_scope` for a missing scope, or a tool error for a policy denial. If the device does not report the new value within the timeout, the result is `unconfirmed`, never `confirmed` (P2).

### Interfaces

| Interface | Protocol | Authentication |
|---|---|---|
| AI client to gateway | MCP Streamable HTTP over HTTPS (spec 2026-07-28) | OAuth 2.1 bearer token, audience-bound |
| AI client to Keycloak | OAuth 2.1 authorization code with PKCE | Owner signs in; pre-registered public client |
| Gateway to Keycloak | HTTPS (discovery, signing keys) | None needed (public metadata) |
| Gateway to device | ESPHome native API | Noise pre-shared key |
| Gateway to owner (approval) | Pending | Pending |

## Phase D: Technology architecture

### Deployment

```mermaid
flowchart TB
    subgraph internet["Internet"]
        le["Let's Encrypt"]
        desec["deSEC<br/>(lab.domain DNS)"]
        nabu["Nabu Casa"]
    end

    subgraph lan["Household network (no inbound ports for the lab)"]
        laptop["Laptop<br/>(MCP clients)"]
        adg["AdGuard Home x2 (synced)<br/>*.lab.domain to lab Zoraxy"]
        hzx["Household Zoraxy<br/>(not used by the lab)"]
        ha["Home Assistant"]
        esp["ESPHome controller<br/>API only, web server removed"]
    end

    router{{"UniFi router<br/>lab allow list"}}

    subgraph labnet["Lab VLAN (separate bridge on one Proxmox node)"]
        zx["LXC: lab Zoraxy<br/>TLS termination,<br/>*.lab wildcard"]
        kclxc["LXC: Keycloak + PostgreSQL"]
        gwlxc["LXC: MCP gateway<br/>holds device key"]
    end

    laptop -- "DNS" --> adg
    laptop -- "HTTPS 443" --> router
    router -- "443 only" --> zx
    zx -- "HTTP (inside lab)" --> kclxc
    zx -- "HTTP (inside lab)" --> gwlxc
    gwlxc -- "signing keys via<br/>lab Zoraxy" --> zx
    gwlxc -- "DNS 53, device 6053" --> router
    router --> adg
    router --> esp
    ha -- "6053 Noise" --> esp
    zx -- "DNS-01 challenge" --> desec
    zx -- "ACME" --> le
    ha --- nabu
```

### Network flows

Every flow between the lab VLAN and the household network crosses the router, which allows only the flows marked "router" below and blocks the rest. Flows inside the lab VLAN do not reach the router and are not filtered.

| From | To | Port | Purpose |
|---|---|---|---|
| MCP client (household) | Lab Zoraxy | 443 | MCP calls; Keycloak sign-in (router) |
| Owner's admin machine | Lab Zoraxy | admin port | Proxy configuration (router) |
| Lab Zoraxy | Keycloak LXC | 8080 | Proxied Keycloak (inside lab) |
| Lab Zoraxy | Gateway LXC | to be set | Proxied MCP endpoint (inside lab) |
| Lab VLAN | AdGuard Home | 53 | Name resolution (router) |
| Gateway LXC | Lab Zoraxy | 443 | Keycloak discovery and signing keys, using the public HTTPS name so the issuer matches (inside lab) |
| Gateway LXC | ESPHome controller | 6053 | Native API (Noise); the only lab-to-device flow (router) |
| Lab VLAN | Internet | 443 | Package and image updates (router) |
| Home Assistant | ESPHome controller | 6053 | Unchanged |
| Lab Zoraxy | deSEC, Let's Encrypt | 443 | Certificate issuance and renewal only (router) |

The ESPHome native API allows several clients at once (`max_connections` defaults to 5 on ESP32), so the gateway and Home Assistant can both stay connected.

## Gap analysis

| Gap (baseline to target) | Addressed by | Status |
|---|---|---|
| Ungoverned direct path (web server) | ADR 0001 | Done |
| No identity for AI clients | ADR 0004, ADR 0005; Keycloak setup | Keycloak being installed |
| No TLS on the LAN for lab services | ADR 0006; deSEC, Zoraxy, AdGuard | Being set up |
| Lab work could affect household services | ADR 0006 (amended): lab VLAN, separate bridge, dedicated lab proxy, router rules | Being set up |
| No governed API for the device | Gateway, read-only first (P8) | Not started |
| No bounds stricter than the device | Gateway policy | Not started |
| No human approval for high-risk actions | Approval ADR | Decision open |
| No audit of AI actions | Audit writer; ADR 0007 | Decided; not built |
| No threat model | Threat model document and tests | Not started |

## Open items

- ADR on the approval mechanism.
- The gateway's port and canonical MCP address (`https://boiler.lab.<domain>/mcp`) are set during implementation.
- Roadmap of increments (phases E and F), starting with read-only tools.
