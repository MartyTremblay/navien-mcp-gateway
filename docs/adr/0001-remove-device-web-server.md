# 0001. Remove the device's web server to close a path around the gateway

Status: accepted (2026-10-08)

Principles: applies P3 (controls independent of the device), P7 (fail safe) and P10 (enterprise pattern by default). Trades off the vision's "no firmware changes" scope.

## Context

The gateway governs only the calls that go through it. While verifying that Home Assistant and the gateway could share the device's native API, we found that the device's ESPHome firmware also ran the built-in web server on port 80 without authentication. An unauthenticated request returned HTTP 200. ESPHome's web server can change entities as well as display them, so anything on the local network could have changed the boiler's settings directly, bypassing authentication, policy, approval and audit.

In enterprise terms, this is a system of record that still accepts direct database connections after an API gateway has been put in front of it.

The [architecture vision](../architecture/01-vision.md) put firmware changes out of scope, to keep the gateway non-invasive (P9).

Options considered:

1. **Leave it and document it as an accepted risk.** No firmware change, but every control in the gateway can be bypassed, which undermines the project's purpose.
2. **Add authentication to the web server.** This closes casual access, but it keeps a second control path with its own credentials, no scopes, no policy and no audit.
3. **Remove the web server.** Nothing uses it: Home Assistant connects through the native API, and the gateway will too.

## Decision

Remove the web server from the device's firmware configuration (option 3), with `web_server: !remove` in the device's board configuration on the owner's firmware branch. The shared package that enables it for other boards is left unchanged.

Separately, an opt-in documentation change was offered upstream ([htumanyan/navien#93](https://github.com/htumanyan/navien/pull/93)) so other users can add a login if they keep the web server. Forcing authentication on a community hobby project would have broken existing builds, so the upstream change only adds guidance.

## Consequences

- Verified after flashing on 2026-10-08: port 80 refuses connections, and the native API port is still open.
- The only remaining direct path is the native API. It is encrypted, and its key is held by Home Assistant and the gateway. Home Assistant's direct connection is a known, accepted second path (see the vision's non-goals) and will be covered in the threat model.
- The firmware's captive portal still serves a page, but only when the device falls back to its own Wi-Fi access point, which is password protected. It is kept as the recovery path.
- The device has no browser-based diagnostics. Logs are still available through the native API and the ESPHome dashboard.
- The vision's scope now allows firmware changes when, and only when, they remove a path that bypasses the gateway.
- The threat model must list every direct path to the device and include a test that port 80 stays closed after future firmware updates.
