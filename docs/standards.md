# Frameworks and standards inventory

Every framework, standard and specification this project relies on, where it's applied, and whether the documentation names it explicitly or the code uses it without naming it. Compiled 2026-10-09 from the repository's docs and code.

A small project for one boiler touches 40 of them (some rows group related items). Keeping that many in view, with the right clause for each decision, is one place where an AI assistant helped the architecture work; see [How it's built](../README.md#how-its-built). Every citation was checked against its source rather than taken from memory.

**Status:** *Explicit* means a document names it. *Implicit* means the code or configuration depends on it but the docs don't name it.

## Architecture and governance

| Framework | Used for | Where | Status |
|---|---|---|---|
| TOGAF Architecture Development Method (ADM) | Lightweight method: principles, vision, B to D views, roadmap, compliance checks | [architecture/](architecture/README.md) | Explicit |
| Architecture Decision Records (ADRs) | One decision per record: context, options, decision, consequences | [adr/](adr/README.md) | Explicit |
| NIST AI Risk Management Framework (AI RMF) | Planned requirements register mapping controls to Govern, Map, Measure, Manage | [roadmap](architecture/03-roadmap.md), [threat model](threat-model.md) | Explicit (mapping planned, increment 5) |
| ISO/IEC 42001 (AI management systems) | How the approach would scale to an organization; not applied directly | [README](../README.md) | Explicit (reference only) |

## Security and risk

| Standard or practice | Used for | Where | Status |
|---|---|---|---|
| STRIDE | Threat categories | [threat model](threat-model.md) | Explicit |
| OWASP Top 10 for LLM Applications (2025) | LLM01 prompt injection, LLM02 sensitive information disclosure, LLM03 supply chain, LLM06 excessive agency, LLM09 misinformation | [threat model](threat-model.md) | Explicit |
| Least privilege, defense in depth, fail safe (fail closed) | Architecture principles P1, P3, P7 | [principles](architecture/00-principles.md) | Explicit |
| Network segmentation | Lab VLAN with router allow-list | [ADR 0006](adr/0006-hosting-and-tls.md) | Explicit |
| Separation of environments (per-environment ingress) | Dedicated lab reverse proxy | [ADR 0006](adr/0006-hosting-and-tls.md) | Explicit |

## AI agent protocol

| Specification | Used for | Where | Status |
|---|---|---|---|
| Model Context Protocol, revision 2026-07-28 | Streamable HTTP transport, stateless requests, routing headers (`Mcp-Method`, `Mcp-Name`), header-body consistency (`HeaderMismatch`), `Origin` validation | [ADR 0003](adr/0003-streamable-http-transport.md), `server.py` | Explicit |
| Model Context Protocol, revision 2025-11-25 | Compatibility for earlier clients (served statelessly) | [ADR 0003](adr/0003-streamable-http-transport.md) | Explicit |
| MCP Authorization (revision 2026-07-28) | Resource-server role, discovery, scopes, step-up challenges | [ADR 0004](adr/0004-oauth-2-1-resource-server.md) | Explicit |
| MCP tool annotations | `readOnlyHint` and related hints on the status tool | `server.py` | Implicit |

## Identity and access

| Standard | Used for | Where | Status |
|---|---|---|---|
| OAuth 2.1 (IETF draft) | Authorization framework; the gateway is a resource server | [ADR 0004](adr/0004-oauth-2-1-resource-server.md) | Explicit |
| PKCE (RFC 7636), S256 | Required for every public client | [ADR 0005](adr/0005-keycloak-identity-provider.md) | Explicit by name; RFC implicit |
| Resource Indicators (RFC 8707) | Tokens bound to the gateway's URL (`aud`) | ADR 0004, ADR 0005, `auth.py` | Explicit |
| Protected Resource Metadata (RFC 9728) | How clients discover the authorization server | ADR 0004, `server.py` (SDK) | Explicit |
| Authorization Server Metadata (RFC 8414) and OpenID Connect Discovery | Discovering Keycloak's endpoints and keys | ADR 0004, `auth.py` | Explicit |
| Authorization Server Issuer Identification (RFC 9207) | `iss` in authorization responses | ADR 0004, ADR 0005, `oauth_pkce_check.py` | Explicit |
| OAuth Client ID Metadata Documents (IETF draft) | Considered; clients pre-registered instead | ADR 0004, ADR 0005 | Explicit |
| Dynamic Client Registration (RFC 7591) | Blocked by policy | ADR 0004, ADR 0005 | Explicit by name; RFC implicit |
| Bearer Token Usage (RFC 6750) | `Authorization: Bearer`, `WWW-Authenticate` challenges, `insufficient_scope` | `server.py`, ADR 0004 | Implicit |
| JSON Web Token (RFC 7519) | Access token format and claims | `auth.py` | Implicit |
| JSON Web Key Set (RFC 7517) | Realm signing keys | `auth.py` | Implicit |
| JWT Profile for OAuth 2.0 Access Tokens (RFC 9068) | Shape of Keycloak's access tokens (`typ`, `azp`, `scope`) | `auth.py` | Implicit |
| Refresh token rotation (OAuth 2.1, public clients) | Keycloak realm setting for the client's refresh tokens | [ADR 0005](adr/0005-keycloak-identity-provider.md) | Explicit (practice) |
| One-time passwords (TOTP, RFC 6238) | Second factor for administrator and user sign-in | Runbooks | Implicit |

## Transport, web and DNS

| Standard | Used for | Where | Status |
|---|---|---|---|
| TLS 1.3 | HTTPS to the lab reverse proxy | ADR 0006 | Explicit (TLS); version implicit |
| `Host` and `Origin` validation | DNS-rebinding protection | ADR 0003, `server.py` | Explicit |
| Server-Sent Events | Streamed MCP responses and `subscriptions/listen` | ADR 0003, ADR 0006 | Explicit |
| `X-Forwarded-*` headers | Reverse proxy to Keycloak | ADR 0006 | Explicit |
| ACME (RFC 8555), DNS-01 challenge | Certificate issuance with no inbound ports | ADR 0006 | Explicit by name; RFC implicit |
| Certificate Transparency | Why the certificate is a wildcard | ADR 0006 | Explicit |
| DNS delegation (NS records) and DNSSEC | Lab subdomain delegated to a separate DNS host | ADR 0006 | Explicit |
| IEEE 802.1Q (VLANs) | Lab network separation | ADR 0006 | Explicit (VLAN); standard implicit |

## Device and cryptography

| Standard | Used for | Where | Status |
|---|---|---|---|
| ESPHome native API | Reading the boiler's controller | ADR 0002, `device.py` | Explicit |
| Noise Protocol Framework (`Noise_NNpsk0_25519_ChaChaPoly_SHA256`) | Encryption of the device connection | ADR 0002 | Explicit (Noise); suite implicit |
| SHA-256 | Audit hash chain | [ADR 0007](adr/0007-audit-store.md), `audit.py` | Explicit |

## Licensing

| Licence | Where | Status |
|---|---|---|
| MIT | [LICENSE](../LICENSE) | Explicit |

## Gaps to close

- Name the implicit standards where they matter in the ADRs (for example RFC 6750 and RFC 7519 in ADR 0004), so the reasoning is traceable without reading the code.
- Map controls to NIST AI RMF functions in the requirements register (increment 5).
