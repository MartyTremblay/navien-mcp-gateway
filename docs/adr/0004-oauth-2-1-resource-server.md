# 0004. OAuth 2.1, with the gateway as a resource server only

Status: accepted (2026-10-08)

Principles: applies P1 (least privilege for agents), P5 (every call is accountable), P6 (secrets stay server-side), P7 (fail safe) and P10 (enterprise pattern by default).

## Context

[ADR 0003](0003-streamable-http-transport.md) chose Streamable HTTP, where every request carries its own credentials. This ADR decides what those credentials are and who issues them.

The MCP specification ([revision 2026-07-28, Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)) defines three roles:

- "A protected *MCP server* acts as an OAuth 2.1 resource server, capable of accepting and responding to protected resource requests using access tokens."
- "An *MCP client* acts as an OAuth 2.1 client, making protected resource requests on behalf of a resource owner."
- "The *authorization server* is responsible for interacting with the user (if necessary) and issuing access tokens for use at the MCP server." It "may be hosted with the resource server or a separate entity."

## Options considered

1. **Static bearer tokens.** Simple, and the SDK's `TokenVerifier` interface would allow a later switch. But there is no standard way to issue, expire or revoke them, no user identity behind them, and MCP clients cannot discover how to get one. This is the shortcut an enterprise would not accept for production.
2. **OAuth 2.1 with the authorization server built into the gateway.** The Python SDK includes an `OAuthAuthorizationServerProvider`, so this is possible. But the gateway would then hold token-signing keys and user credentials as well as the device key. A compromise of the one process exposed to clients would expose everything.
3. **OAuth 2.1 with a separate authorization server (identity provider).** The gateway only validates tokens. Issuing tokens, authenticating users and registering clients belong to a dedicated identity service.

## Decision

Use OAuth 2.1 with a separate authorization server (option 3). The gateway is a resource server only. There is no interim static-token phase. The choice of identity provider is a separate decision ([ADR 0005](README.md), pending).

What the gateway does, following the specification:

- **Advertises its authorization server** through OAuth 2.0 Protected Resource Metadata (RFC 9728) at `/.well-known/oauth-protected-resource`. The spec says "MCP servers **MUST** implement OAuth 2.0 Protected Resource Metadata."
- **Challenges unauthenticated requests** with HTTP 401 and a `WWW-Authenticate` header carrying `resource_metadata` and the `scope` needed, so clients ask only for what the operation requires.
- **Validates every token** on every request: signature, expiry, issuer and audience. The spec says "MCP servers **MUST** validate that access tokens were issued specifically for them as the intended audience" (RFC 8707). A token issued for any other service is rejected, even if it is valid there.
- **Never passes a token on.** The spec says "MCP servers **MUST NOT** accept or transit any other tokens." The gateway talks to the device with its own encryption key, so client tokens never leave the gateway.
- **Checks scopes per tool.** Tools that read require `boiler:read`, and tools that write require `boiler:write`. Scopes do not imply each other: write does not include read, so a client asks for exactly what it uses. A call with too little scope gets HTTP 403 with `error="insufficient_scope"` and every scope the call needs, in one challenge, as the spec recommends.
- **Fails closed.** If the token cannot be validated, for example because the authorization server's signing keys cannot be fetched, the call is denied (P7).

What the authorization server must support:

- OAuth 2.1 with PKCE for the authorization code flow.
- Resource indicators (RFC 8707), so tokens are issued with the gateway as their audience.
- Authorization server metadata (RFC 8414) or OpenID Connect Discovery.
- Client registration through Client ID Metadata Documents, which the spec says clients and servers "**SHOULD** support", or pre-registration. Dynamic Client Registration "is deprecated" in this revision and stays off.
- Issuer identification in authorization responses (RFC 9207), which the spec expects to become a **MUST**.

## Consequences

- **Two identities in every audit record.** Each token identifies the user who granted access (the subject) and the client acting for them (the client ID). The audit trail can answer both "which person allowed this" and "which agent did it". This is the core of the agent identity question for enterprises.
- **Agents acting on their own behalf.** An automated agent with no user present would use the client credentials grant. The SDK includes a client credentials extension, and the specification allows such clients to abort rather than step up when scope is insufficient. This is deferred until an automated agent is needed. When it is, the agent gets its own client and scopes, never a user's.
- **Enterprise single sign-on is a known extension.** The SDK also includes an identity assertion extension (enterprise-managed authorization), where an organization's identity provider governs which agents can reach which MCP servers. It is out of scope here and noted for the whitepaper.
- **The identity provider becomes critical.** If it is down, no new tokens are issued and, because the gateway fails closed, no calls succeed once existing tokens expire. Token lifetime is the trade-off between availability and how quickly revocation takes effect. Short-lived tokens are preferred.
- **Support for newer standards varies.** Resource indicators, Client ID Metadata Documents and RFC 9207 are newer than core OAuth, and identity providers support them unevenly. ADR 0005 must check each candidate against the list above.
- **Client support needs checking.** Each MCP client used with the gateway must support MCP's OAuth flow for this specification revision. This is confirmed per client during implementation.
- **More setup.** The gateway cannot be used until an identity provider is running and configured. Testing needs tokens from that provider too, with test clients and test users.
