# 0003. Streamable HTTP as the only transport

Status: accepted (2026-10-08)

Principles: applies P1 (least privilege for agents), P5 (every call is accountable), P6 (secrets stay server-side) and P7 (fail safe).

## Context

MCP defines two standard transports in the current specification ([revision 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)):

- **stdio:** "newline-delimited messages over the standard streams of a client-launched subprocess."
- **Streamable HTTP:** "each message is an HTTP POST to a single MCP endpoint; replies arrive as a JSON object or a request-scoped SSE stream."

The older HTTP+SSE transport "has been deprecated since protocol version `2025-03-26`", and the spec says "New implementations **SHOULD NOT** adopt it."

The gateway's purpose is to authenticate each client, authorize each call and audit it. The transport decides whether that is possible.

## Options considered

1. **stdio.** The AI client launches the gateway as a local subprocess. There is no network boundary: the gateway runs as the user who launched it, it cannot tell one client from another, and the device key would have to be on every machine that runs a client. Authentication, per-client scopes and keeping secrets server-side would all be impossible to enforce.
2. **Streamable HTTP.** The gateway runs as an independent service that clients connect to over HTTP. Every request can carry a bearer token, and the device key stays on the gateway host.
3. **Both:** stdio for local development, HTTP for real use. Two entry points means two paths to keep governed. A stdio path without authentication would be a way around the gateway's own controls, the same problem [ADR 0001](0001-remove-device-web-server.md) closed on the device.

## Decision

Streamable HTTP only (option 2), following the 2026-07-28 revision of the specification. stdio and the deprecated HTTP+SSE transport are not offered. Tests exercise the server through the SDK in-process rather than through a separate unauthenticated entry point.

Network exposure, until a hosting decision says otherwise:

- Bind to localhost by default. The spec says that "When running locally, servers **SHOULD** bind only to localhost (127.0.0.1) rather than all network interfaces (0.0.0.0)."
- Listen on the local network only behind TLS and with authentication.
- No exposure to the internet. Remote access, if ever needed, gets its own ADR (for example a VPN rather than an open port).

Required by the specification and enforced from the first release:

- **Origin validation:** "Servers **MUST** validate the `Origin` header on all incoming connections to prevent DNS rebinding attacks", and reject an invalid one with HTTP 403.
- **Header and body consistency:** the server rejects any request whose `Mcp-Method`, `Mcp-Name` or `MCP-Protocol-Version` headers do not match the body, with HTTP 400 and `HeaderMismatch`.

## Consequences

- **Per-request authentication and audit.** In the 2026-07-28 revision there are no protocol-level sessions ("Removal of protocol-level sessions"). Every tool call is its own HTTP POST with its own credentials, so each call is authenticated, authorized and audited on its own (P5). Nothing relies on a session established earlier.
- **Designed for intermediaries.** The spec mirrors the method and tool name into headers "so that intermediaries (load balancers, gateways, observability tooling) can route and inspect requests without parsing the body." An enterprise could put a standard API gateway in front of this service and apply coarse policy, such as rate limits per tool, from the headers alone. The spec's header-body consistency rule exists to stop that pattern being abused ("a load balancer routing on the header value while the MCP server executes based on the body value").
- **Client compatibility is a risk.** The 2026-07-28 revision is recent and changes Streamable HTTP's behaviour. Some MCP clients may still speak the earlier session-based revisions (2025-03-26 to 2025-11-25). The Python SDK appears to include both modern and earlier handlers. During implementation, confirm which revisions the SDK serves and which revision each intended client uses. Supporting an earlier revision would bring back sessions, and with them session-ID handling that the threat model must cover.
- **More to run.** The gateway is now a service with a port, TLS and a process to keep running, rather than a subprocess a client launches. Where it runs is a separate decision.
- **Local development** uses the same HTTP path as production, with test credentials. There is no shortcut that skips authentication.
