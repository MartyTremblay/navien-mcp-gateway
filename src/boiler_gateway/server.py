"""The MCP gateway: Streamable HTTP, OAuth resource server, policy, audit (ADR 0003, 0004, 0007).

Request path, outermost first:

1. The SDK's transport security: `Host` and `Origin` checks against DNS rebinding.
2. The SDK's bearer authentication, using `GatewayTokenVerifier` (auth.py).
3. `GatewayPolicyMiddleware` (here): audits every MCP request and refuses tool
   calls whose token lacks the tool's scopes, with a proper 403
   `insufficient_scope` challenge. It reads the tool name from the
   `Mcp-Method` and `Mcp-Name` headers, which the SDK later checks against the
   body (`HeaderMismatch`), so a lying header can only cause a denial.
4. The SDK's `RequireAuthMiddleware` (401 challenge with resource metadata).
5. The tool itself, which checks scopes again (defense in depth, and for
   clients that don't send the routing headers) and records the outcome.

Any audit failure makes the request fail (P5, P7).
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.inbound import decode_header_value
from mcp_types import ToolAnnotations
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from boiler_gateway import policy
from boiler_gateway.audit import AuditError, AuditLog, Identity
from boiler_gateway.auth import GatewayTokenVerifier, JwksKeys, identity_from
from boiler_gateway.config import Settings
from boiler_gateway.device import Device
from boiler_gateway.status import build_status

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"
_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

INSTRUCTIONS = (
    "Read-only access to a home boiler through a governed gateway. Values come from the "
    "boiler's controller; if device_connected is false, treat every value as stale."
)


async def _audit_decision(audit: AuditLog, *args: Any) -> None:
    await asyncio.to_thread(audit.record_decision, *args)


class GatewayPolicyMiddleware:
    """Audit every MCP request and enforce per-tool scopes before dispatch."""

    def __init__(self, app: ASGIApp, audit: AuditLog, resource_metadata_url: str):
        self.app = app
        self.audit = audit
        self.resource_metadata_url = resource_metadata_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        method = headers.get("mcp-method")
        tool = decode_header_value(headers.get("mcp-name")) if method == "tools/call" else None
        request_id = str(uuid.uuid4())
        user = scope.get("user")

        try:
            if not isinstance(user, AuthenticatedUser):
                # Invalid tokens were already audited by the verifier; record the no-token case.
                if "authorization" not in headers:
                    await _audit_decision(
                        self.audit, request_id, Identity(None, None), tool, None, "deny", "no_token"
                    )
                await self.app(scope, receive, send)  # RequireAuthMiddleware answers 401
                return

            who = identity_from(user.access_token)
            if method == "tools/call":
                missing = policy.missing_scopes(tool or "", who.scopes)
                if missing is None:
                    await _audit_decision(
                        self.audit, request_id, who, tool, None, "deny", "unknown_tool"
                    )
                elif missing:
                    await _audit_decision(
                        self.audit, request_id, who, tool, None, "deny", "insufficient_scope"
                    )
                    await self._insufficient_scope(sorted(policy.TOOL_SCOPES[tool]), send)
                    return
                else:
                    await _audit_decision(self.audit, request_id, who, tool, None, "allow")
            else:
                # Listing and other protocol requests: recorded, no device access.
                await _audit_decision(
                    self.audit,
                    request_id,
                    who,
                    None,
                    None,
                    "allow",
                    f"method:{method or 'unknown'}",
                )
        except AuditError:
            log.error("audit write failed; refusing request")
            await JSONResponse({"error": "audit_unavailable"}, status_code=503)(
                scope, receive, send
            )
            return

        token = _REQUEST_ID.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _REQUEST_ID.reset(token)

    async def _insufficient_scope(self, scopes: list[str], send: Send) -> None:
        challenge = (
            f'Bearer error="insufficient_scope", scope="{" ".join(scopes)}", '
            f'resource_metadata="{self.resource_metadata_url}", '
            'error_description="This tool needs additional scope"'
        )
        body = b'{"error":"insufficient_scope"}'
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", challenge.encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_app(
    settings: Settings,
    device: Device,
    audit: AuditLog,
    keys: JwksKeys | None = None,
) -> Starlette:
    keys = keys or JwksKeys(settings.issuer, settings.gateway_jwks_cache_seconds)
    verifier = GatewayTokenVerifier(settings, keys, audit)

    mcp = MCPServer(
        name="boiler-gateway",
        instructions=INSTRUCTIONS,
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=settings.issuer,
            resource_server_url=settings.resource_url,
            required_scopes=policy.SCOPES_SUPPORTED,
            # The verifier checks `aud` itself; the SDK checking again is defense in depth.
            validate_token_resource=True,
        ),
    )

    @mcp.tool(
        name="get_boiler_status",
        title="Boiler status",
        description=(
            "Current boiler state: operating state, heating mode, temperatures, setpoints, "
            "burner level and error state. Read-only."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    async def get_boiler_status() -> dict[str, Any]:
        started = time.perf_counter()
        access = get_access_token()
        who = identity_from(access) if access else Identity(None, None)
        request_id = _REQUEST_ID.get()
        missing = policy.missing_scopes("get_boiler_status", who.scopes)
        if access is None or missing:
            await _audit_decision(
                audit,
                request_id or str(uuid.uuid4()),
                who,
                "get_boiler_status",
                None,
                "deny",
                "insufficient_scope",
            )
            raise ToolError("Not authorized: this tool needs the boiler:read scope.")
        if request_id is None:  # the client didn't send routing headers
            request_id = str(uuid.uuid4())
            await _audit_decision(audit, request_id, who, "get_boiler_status", None, "allow")

        result = build_status(device.snapshot())
        latency_ms = round((time.perf_counter() - started) * 1000)
        await asyncio.to_thread(
            audit.record_outcome,
            request_id,
            "ok" if result["device_connected"] else "unconfirmed",
            latency_ms,
            None if result["device_connected"] else "device_disconnected",
        )
        return result

    app = mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.gateway_allowed_hosts,
            allowed_origins=settings.gateway_allowed_origins,
        ),
        host=settings.gateway_bind_host,
    )

    # Put the policy layer just inside authentication, around the MCP endpoint.
    metadata_url = str(build_resource_metadata_url(settings.gateway_resource_url))
    for route in app.router.routes:
        if isinstance(route, Route) and route.path == MCP_PATH:
            route.app = GatewayPolicyMiddleware(route.app, audit, metadata_url)
            break
    else:  # pragma: no cover - would mean the SDK changed shape
        raise RuntimeError("MCP route not found; refusing to start without the policy layer")

    sdk_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a: Starlette):
        await device.start()
        try:
            async with sdk_lifespan(a):
                yield
        finally:
            await device.stop()

    app.router.lifespan_context = lifespan
    return app
