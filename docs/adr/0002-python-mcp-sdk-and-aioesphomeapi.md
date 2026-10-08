# 0002. Python with the official MCP SDK and aioesphomeapi

Status: accepted (2026-10-08)

Principles: applies P2 (the device is the source of truth), P7 (fail safe) and P10 (enterprise pattern by default). Trades off part of P10 by building the control plane rather than buying one.

## Context

The gateway has two sides, and each needs a library:

- **Client side:** an MCP server with Streamable HTTP and bearer-token authentication, with a path to OAuth 2.1.
- **Device side:** a client for the ESPHome native API with Noise encryption. The device rejects unencrypted connections, and every write has to be read back (P2), so the client must handle encrypted sessions and live state updates reliably.

The device side is the higher-risk choice. It controls a gas appliance, and a weak client there turns into wrong or unconfirmed writes.

The owner is comfortable reviewing Python.

## Options considered

1. **Python: official `mcp` SDK plus `aioesphomeapi`.**
2. **TypeScript: official `@modelcontextprotocol/sdk` plus a community ESPHome client.**
3. **A split design: an MCP front end plus a separate device adapter service.** The most enterprise-like shape, since device credentials sit in a process that faces no clients (P6). But it means two services and an internal API for one device.
4. **Buy instead of build:** an off-the-shelf API or MCP gateway product for authentication and authorization, with a thin MCP server behind it. This is often the right enterprise answer, but this project exists to build and understand the controls.
5. **Go or C#:** MCP SDKs exist, but no mature ESPHome client.

### Device client due diligence (checked 2026-10-08)

| Library | Noise | Maintainer | Weekly downloads | Notes |
|---|---|---|---|---|
| `aioesphomeapi` 46.8.0 (Python) | Yes, using the `noiseprotocol` library | ESPHome organization | about 87,000 (PyPI) | Used by Home Assistant's ESPHome integration |
| `esphome-client` 2.0.0 (Node) | Yes, its own Noise implementation on Node's built-in `crypto` | One maintainer | 886 (npm) | Zero dependencies; runtime for `homebridge-ratgdo` |
| `@2colors/esphome-native-api` 1.3.6 (Node) | Yes, using `noise-c.wasm` (last published April 2023) | One maintainer | 1,229 (npm) | |
| `@webarray/esphome-native-api` 1.0.5 (Node) | Partial | One maintainer | 321 (npm) | Package includes `encrypted-connection-broken.js` |
| `esphome-ts` 5.0.0 (Node) | No Noise code found | One maintainer | 14 (npm) | Cannot connect to this device |

Download counts measure adoption, not quality. None of these libraries has been tested against the device yet.

### MCP SDK (checked 2026-10-08)

The Python `mcp` package (2.3.0, Python 3.10 or later) includes a Streamable HTTP server, a `TokenVerifier` protocol for checking bearer tokens, `AuthSettings` with server-wide `required_scopes`, bearer-auth middleware, and an OAuth authorization server provider.

## Decision

Use Python, with the official `mcp` SDK for the MCP server and `aioesphomeapi` for the device (option 1), in a single service.

- `esphome-client` is the credible TypeScript alternative. It was not chosen because of who maintains it, how widely it is used, and its custom Noise implementation, not because it lacks features.
- Option 3 (split service) is the documented target if the gateway ever serves more than one device or needs stronger isolation of device credentials. The code will keep the device adapter behind its own interface so the split stays cheap.
- Option 4 (buy) is noted as what an enterprise would usually do for authentication and authorization at scale.

## Consequences

- The device client is the same library Home Assistant relies on, maintained by the ESPHome project, so protocol changes and fixes are likely to arrive there first.
- Authentication starts with a `TokenVerifier` implementation. Static tokens and, later, OAuth access tokens can sit behind the same interface (see the auth ADR).
- Per-tool scope checks (`boiler:read`, `boiler:write`) are gateway code, since the SDK's `required_scopes` applies to the whole server.
- One process holds the device key and serves clients. That is accepted for now and revisited if option 3 is adopted.
- `aioesphomeapi` releases often (major version 46 at the time of writing), so dependencies are pinned and upgraded deliberately, with read-back tests run against the device after each upgrade.
- Some MCP features may reach the TypeScript SDK before the Python SDK. That is acceptable, since this gateway needs only tools, resources, Streamable HTTP and bearer authentication.
