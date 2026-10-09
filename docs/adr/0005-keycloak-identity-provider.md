# 0005. Keycloak as the identity provider

Status: accepted (2026-10-08)

Principles: applies P1 (least privilege for agents), P7 (fail safe) and P10 (enterprise pattern by default).

## Context

[ADR 0004](0004-oauth-2-1-resource-server.md) made the gateway an OAuth 2.1 resource server and listed what the separate authorization server must support. The owner wants a free product, self-hosted in an existing Proxmox lab.

The most important requirement is RFC 8707 resource indicators: the authorization server must issue tokens whose audience (`aud`) is the gateway's own address, so the gateway can reject tokens meant for anything else. The MCP specification also expects Client ID Metadata Documents and RFC 9207 issuer identification, which are newer and less widely supported.

## Options considered

Four free, self-hostable identity providers were checked against the ADR 0004 list on 2026-10-08, using each project's documentation, release notes and source code. All four have Proxmox VE community scripts ([community-scripts.org](https://community-scripts.org/)), so ease of installation did not separate them.

| Requirement | Keycloak 26.8.0 | Authelia 4.39.28 | Zitadel 4.19.4 | authentik 2026.8.3 |
|---|---|---|---|---|
| RFC 8707: gateway address in token `aud` | Yes, experimental feature | Yes; broken in 4.39.21 and 4.39.22, changing again | No: accepted but ignored | No |
| PKCE (S256) required per client | Yes | Yes | Yes | Only if the client sends it |
| RFC 8414 metadata or OIDC Discovery | Both | Both | OIDC only | Both |
| Client ID Metadata Documents | Yes, experimental feature | No | Not released | No |
| RFC 9207 issuer identification | Yes | Yes | No | No |
| Plain custom scopes (`boiler:read`) | Yes | Yes, with log warnings | No: project roles with a URN prefix | Yes |
| Official MCP guide | Yes | No | Mentions MCP clients in its registration guide | No |
| Community script default size | 2 CPU, 2 GB RAM, PostgreSQL | 1 CPU, 512 MB RAM, SQLite | 1 CPU, 1 GB RAM, PostgreSQL | 4 CPU, 8 GB RAM, PostgreSQL |
| Licence | Apache 2.0 | Apache 2.0 | AGPL-3.0 | MIT (core) |

Key evidence:

- **Keycloak** documents RFC 8707 as experimental: "If the feature is disabled, Keycloak does not recognize the `resource` parameter." With it enabled, "Keycloak issues the access token whose `aud` claim includes only the value" ([Keycloak MCP guide](https://www.keycloak.org/securing-apps/mcp-authz-server)). The same guide lists MCP 2025-03-26 as supported and later revisions, including 2026-07-28, as experimental.
- **Zitadel** documents that "The `resource` parameter (RFC 8707) is accepted on the authorization code flow but ignored, so it does not narrow `aud`" ([Zitadel guide](https://zitadel.com/docs/guides/integrate/dynamic-client-registration)).
- **authentik**'s source says "RFC 8707 resource indicators are not implemented" (`authentik/providers/oauth2/token/token_exchange.py` at `version/2026.8.3`).
- **Authelia** fixed a regression in which "authorization_code token exchange rejects every RFC 8707 resource indicator" ([issue #12970](https://github.com/authelia/authelia/issues/12970), fixed in 4.39.23). It has no Client ID Metadata Documents and no dynamic registration, so it only works with MCP clients that accept a pre-registered client ID.

## Decision

Use Keycloak, self-hosted in a Proxmox LXC container with PostgreSQL.

- **Version pinned** to the 26.8 line. The community script installs the latest release, so the installed version is recorded and upgrades are deliberate changes, not something that happens on a rerun.
- **Install script read before running.** The script runs as root on the Proxmox host and downloads code from the internet. Reading it first is a small supply-chain control.
- **Resource indicators enabled** (`--features=resource-indicators`), with the gateway's canonical address configured as the resource URI of a resource-server client.
- **Clients pre-registered**, as public clients requiring PKCE with S256. Client ID Metadata Documents stay off for now: the household has few clients, and pre-registration does not depend on an experimental feature.
- **Self-registration blocked.** Dynamic Client Registration is restricted with client registration policies so no client can register itself. The MCP specification deprecates it.
- **Scopes** `boiler:read` and `boiler:write` as client scopes with "Include in token scope" on, optional per client so each client gets only what it is granted.
- **Short-lived access tokens**, starting at 5 minutes, validated by the gateway against Keycloak's published signing keys.

Runner-up: Authelia, for its small footprint and working RFC 8707 support, if a lighter identity provider is ever needed and every MCP client accepts pre-registered client IDs.

## Consequences

- The gateway's tokens will be audience-bound as the MCP specification requires, which neither Zitadel nor authentik could provide today.
- **The two MCP-critical features are experimental.** Resource indicators and Client ID Metadata Documents may change between minor releases. Mitigations:
  - a test, run after every Keycloak upgrade, that a token requested with the gateway's `resource` value has exactly that value in `aud`;
  - a documented fallback if the feature misbehaves: a fixed audience mapper on the client scope, with the gateway still checking `aud` itself.
- **Operations cost.** Keycloak needs about 2 GB of RAM and a PostgreSQL database, which is a lot for one boiler. That is accepted for its enterprise relevance (P10). The database needs backups, since losing it means re-creating clients and users.
- **TLS is required.** Keycloak should be served over HTTPS on the local network. This depends on the open hosting and TLS decision.
- **Availability.** If Keycloak is down, no new tokens are issued, and once existing tokens expire (within 5 minutes) the gateway denies all calls (P7). For one household, that trade-off favours safety over availability.
- **Upgrade path.** When Client ID Metadata Documents leave experimental status, revisit pre-registration, since it would let MCP clients connect without manual setup.
- Keycloak experience transfers directly to enterprise work. Its Red Hat-supported build is common in large organizations.

## Verification (2026-10-09)

Tested against Keycloak 26.8 with the `resource-indicators` feature enabled, using [`tools/oauth_pkce_check.py`](../../tools/oauth_pkce_check.py) and a pre-registered public client (authorization code with PKCE S256, consent required):

- **Audience binding works.** A token requested with `resource=https://boiler.lab.<domain>/mcp` had exactly that value as `aud`, plus the person (`sub`), the agent (`azp`), only the requested scope, and a 300-second lifetime. The authorization response carried `iss` as RFC 9207 requires.
- **Unknown resources are refused.** A request with `resource=https://example.org/not-the-gateway` failed at the token endpoint with `invalid_target`: "The requested resource is invalid, missing, unknown, or malformed." No token was issued.
- **Self-registration is blocked by configuration.** The anonymous Trusted Hosts policy has no trusted hosts. Checked by inspection, not by a live registration attempt.
- **Data minimization.** Keycloak's default `profile` and `email` scopes were removed from the client, so tokens don't carry the person's name or email address, which the gateway doesn't need.

Two setup mistakes surfaced and were fixed: the boiler scopes weren't assigned to the client at first (`invalid_scope`), and the PKCE setting has moved in 26.8 to the client's Capability config.

### First real client (2026-10-09)

Claude Code 2.1.281 completed the sign-in, but its token had `aud: ["boiler-gateway", "account"]`: it did not send the RFC 8707 `resource` parameter, so Keycloak fell back to the client's audience mapper, and the realm's default `roles` scope added `account`. The gateway refused the token (`invalid_token:wrong_audience`, audited). That is the control working against a legitimate client.

The fallback in this ADR was applied to that one client: its dedicated scope now carries an Audience mapper with the gateway's URL as a custom audience, and the `roles` scope was removed from it. The next token had `aud` equal to the gateway's URL only, and the call succeeded. The gateway's validation didn't change.

The client also asks for `offline_access`, so it holds a refresh token. Refusing the scope would make Keycloak reject the whole sign-in, so the mitigation is in the realm: refresh token rotation and a maximum offline session lifetime.

