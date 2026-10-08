# navien-mcp-gateway

A governed MCP server in front of the ESPHome controller on Marty's Navien boiler. AI clients (and Home Assistant) talk to the boiler only through this gateway, which enforces authentication, authorization, policy and audit logging.

This is a learning project: the goal is to practise enterprise AI architecture patterns on a real, low-stakes device, not just to get a working tool. Prefer the pattern an enterprise would use, and explain the trade-off when choosing a simpler one.

## Goals

1. Expose the boiler as MCP tools and resources (read state, change a small set of settings).
2. Authenticate clients and authorize per tool with scopes (e.g. `boiler:read`, `boiler:write`).
3. Enforce policy on writes: value bounds, rate limits, and human approval for risky actions.
4. Audit every call: who, which tool, arguments, policy decision, result, latency. Structured logs; OpenTelemetry tracing is a stretch goal.
5. Keep device credentials server-side. Clients never see the ESPHome API key.
6. Write a threat model (prompt injection, over-broad tools, stolen client token) and test against it.

## Non-goals (for now)

- Replacing Home Assistant's own ESPHome integration. HA keeps its direct connection; the gateway is a second, governed path.
- Multi-device or multi-tenant support. One boiler, one household.

## The device

| Item | Value |
|---|---|
| Boiler | Navien NHB-110H, heat-only, one space-heating zone + indirect DHW tank |
| Controller | Waveshare ESP32-S3-RS485-CAN on the boiler's NaviLink RS485 port |
| Network | LAN only; host and address are in `.env` (`ESPHOME_HOST`) and `CLAUDE.local.md` |
| ESPHome native API | port 6053, **Noise-encrypted**: the key goes in `.env`, never commit it |
| ESPHome web server | port 80 is enabled on the device; check its auth before relying on it |
| Firmware source | `github.com/MartyTremblay/navien`, branch `personal-waveshare-deploy` (fork of `htumanyan/navien`) |

Useful entities (ESPHome object names may differ from HA entity IDs; confirm via the API's entity list):

- Read: SH supply/return temp, tank temp ("Outlet Temp" on NHB-H), SH set temp, DHW tank set temp, DHW boiler set temp, heating mode, operating state, burner %, error code/level, error count, gas usage, connection status.
- Write (numbers): `SH Setpoint` (40–82 °C, 0.5 steps), `DHW Setpoint` (40–82 °C, but tank range used is 40–70 °C); water heater / climate target = tank set temp.
- Write (switches/buttons): main power, allow recirculation, hot button. Treat these as high risk.

Protocol facts that matter here:

- The NHB-H only accepts commands framed with system type `0x04`; reliable on INFO builds only with upstream PRs #91 + #82 (both on the personal branch).
- A command is confirmed when the boiler reports the new value (6–9 s). Never assume a write succeeded: read back.
- The ESP latches error codes for 60 s and keeps a persistent error count.

## Safety rules (non-negotiable)

This is a gas appliance in an occupied house.

- Read-only first. Add write tools one at a time, each with explicit bounds and tests.
- Hard bounds in the gateway, independent of the device: SH 40–70 °C, DHW tank 40–60 °C, unless Marty widens them.
- No power off/on, recirculation or hot-button tools without a human-approval step.
- Rate-limit writes (e.g. one per tool per 2 minutes) and log every rejected call.
- Restore anything changed during testing and say so.

## Secrets

- Nothing secret in the repo or in chat: API keys, HA tokens, client tokens go in `.env` (gitignored) or a secret store. `.env.example` lists the names only.
- Ask Marty to place secrets himself; never print them in logs or tool output.

## Decisions made

- Language/SDK: Python, official `mcp` SDK + `aioesphomeapi` (ADR 0002).
- Transport: Streamable HTTP only, MCP spec revision 2026-07-28; localhost by default, LAN only with TLS + auth, no internet (ADR 0003).
- Auth: OAuth 2.1; gateway is a resource server only, separate authorization server; per-tool scopes `boiler:read` / `boiler:write`, no hierarchy; no token passthrough; fail closed (ADR 0004).
- Identity provider: Keycloak 26.8.x (pinned) in a Proxmox LXC with PostgreSQL; resource-indicators feature on; clients pre-registered (public, PKCE S256); DCR blocked; 5-minute access tokens; test that `aud` equals the gateway's address after every upgrade (ADR 0005).
- Hosting/TLS: gateway, Keycloak and a dedicated lab Zoraxy (TLS termination, LAN only) in separate Proxmox LXCs; household Zoraxy not used by the lab; wildcard `*.lab.<domain>` via Let's Encrypt DNS-01 on a subdomain delegated to deSEC with a TXT-only scoped token; AdGuard Home rewrites (two synced servers); lab containers on a dedicated lab VLAN via a separate bridge on one node, with UniFi rules between lab and household networks (no Proxmox firewall, so household services are never affected); never log `Authorization` headers (ADR 0006).

## Decisions still open

Make these deliberately, with a short ADR in `docs/adr/` each. Each ADR names the principles in `docs/architecture/00-principles.md` it applies or trades off. The project follows a lightweight TOGAF ADM; see `docs/architecture/README.md`.

- Approval mechanism for risky writes.
- Where audit logs go (file, SQLite, OpenTelemetry collector).

## Environment notes

- Machine-specific notes (sandbox, push method, time zone, Home Assistant URL) live in `CLAUDE.local.md`, which is gitignored.
- This repo is public: keep IPs, hostnames, URLs, personal dates and anything secret out of committed files.

## Working style

- Plan first for anything structural; keep changes small and reviewable; commit with clear messages.
- Verify against the real device before calling something done, and report failures plainly.
