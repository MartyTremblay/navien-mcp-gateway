"""Bearer token validation (ADR 0004, ADR 0005).

The gateway is an OAuth 2.1 resource server. Every request's access token is
checked here before anything else:

- signed by the realm's current key (fetched from its published JWKS),
- with an allowed algorithm only (never `none`, never a symmetric algorithm),
- issued by the configured issuer,
- for this gateway exactly: `aud` must be the gateway's URL and nothing else,
- unexpired, and an access token rather than an ID token.

If the signing keys can't be fetched, every token is refused (fail closed, P7).
Each refusal is recorded in the audit store with its reason (P5). Tokens are
never logged or recorded; only their `jti` is.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken

from boiler_gateway.audit import AuditError, AuditLog, Identity
from boiler_gateway.config import Settings

log = logging.getLogger(__name__)

FetchJson = Callable[[str], Awaitable[dict[str, Any]]]

# Only refetch keys for an unknown `kid` this often, so bad tokens can't make
# the gateway hammer the authorization server.
_UNKNOWN_KID_REFETCH_SECONDS = 30
_LEEWAY_SECONDS = 30
_SYMMETRIC = {"HS256", "HS384", "HS512"}


class TokenRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class KeysUnavailable(Exception):
    pass


async def _fetch_json(url: str) -> dict[str, Any]:
    def get() -> dict[str, Any]:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)

    return await asyncio.to_thread(get)


class JwksKeys:
    """The realm's signing keys, from its discovery document, cached for a while."""

    def __init__(self, issuer: str, cache_seconds: int, fetch_json: FetchJson = _fetch_json):
        self._issuer = issuer
        self._cache_seconds = cache_seconds
        self._fetch = fetch_json
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def key_for(self, kid: str) -> jwt.PyJWK:
        now = time.monotonic()
        stale = now - self._fetched_at > self._cache_seconds
        unknown = kid not in self._keys
        if stale or (unknown and now - self._fetched_at > _UNKNOWN_KID_REFETCH_SECONDS):
            await self._refresh()
        if self._keys_expired():
            raise KeysUnavailable("signing keys are out of date and could not be refreshed")
        key = self._keys.get(kid)
        if key is None:
            raise TokenRejected("unknown_signing_key")
        return key

    def _keys_expired(self) -> bool:
        return not self._keys or time.monotonic() - self._fetched_at > self._cache_seconds

    async def _refresh(self) -> None:
        async with self._lock:
            try:
                meta = await self._fetch(self._issuer + "/.well-known/openid-configuration")
                if meta.get("issuer") != self._issuer:
                    raise KeysUnavailable("discovery issuer does not match configuration")
                jwks_uri = meta.get("jwks_uri", "")
                if not jwks_uri.startswith("https://"):
                    raise KeysUnavailable("jwks_uri must be https")
                jwks = await self._fetch(jwks_uri)
                keys = {}
                for k in jwks.get("keys", []):
                    if k.get("use", "sig") != "sig" or "kid" not in k:
                        continue
                    try:
                        keys[k["kid"]] = jwt.PyJWK(k)
                    except jwt.PyJWKError:
                        continue  # skip key types we can't use (e.g. encryption keys)
                if not keys:
                    raise KeysUnavailable("no usable signing keys published")
                self._keys = keys
                self._fetched_at = time.monotonic()
            except KeysUnavailable:
                log.warning("signing key refresh failed: discovery or JWKS invalid")
            except Exception as exc:  # noqa: BLE001 - any failure keeps old keys; stale keys fail closed
                log.warning("signing key refresh failed: %s", exc.__class__.__name__)


class GatewayTokenVerifier:
    """Implements the MCP SDK's TokenVerifier protocol."""

    def __init__(self, settings: Settings, keys: JwksKeys, audit: AuditLog | None = None):
        self._issuer = settings.issuer
        self._resource = settings.resource_url
        self._algorithms = [a for a in settings.gateway_token_algorithms if a not in _SYMMETRIC]
        if not self._algorithms:
            raise ValueError("no asymmetric token algorithms configured")
        self._keys = keys
        self._audit = audit

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await self._validate(token)
        except TokenRejected as rej:
            await self._record_rejection(rej.reason)
            return None
        except KeysUnavailable:
            await self._record_rejection("signing_keys_unavailable")
            return None
        return AccessToken(
            token=token,
            client_id=claims["azp"],
            scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"],
            resource=self._resource,
            subject=claims["sub"],
            claims={"iss": claims["iss"], "jti": claims.get("jti")},
        )

    async def _validate(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise TokenRejected("malformed") from None
        alg = header.get("alg")
        if alg not in self._algorithms:
            raise TokenRejected("algorithm_not_allowed")
        kid = header.get("kid")
        if not kid:
            raise TokenRejected("no_key_id")

        key = await self._keys.key_for(kid)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=self._algorithms,
                audience=self._resource,
                issuer=self._issuer,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "azp"]},
            )
        except jwt.ExpiredSignatureError:
            raise TokenRejected("expired") from None
        except jwt.ImmatureSignatureError:
            raise TokenRejected("not_yet_valid") from None
        except jwt.InvalidAudienceError:
            raise TokenRejected("wrong_audience") from None
        except jwt.InvalidIssuerError:
            raise TokenRejected("wrong_issuer") from None
        except jwt.InvalidSignatureError:
            raise TokenRejected("bad_signature") from None
        except jwt.MissingRequiredClaimError as exc:
            raise TokenRejected(f"missing_claim:{exc.claim}") from None
        except jwt.InvalidTokenError:
            raise TokenRejected("invalid") from None

        # The token must be for this gateway only, not for it among others.
        aud = claims["aud"]
        if (aud if isinstance(aud, list) else [aud]) != [self._resource]:
            raise TokenRejected("audience_not_exclusive")
        # Keycloak marks access tokens `typ: Bearer`; refuse ID or refresh tokens.
        if claims.get("typ", "Bearer") != "Bearer":
            raise TokenRejected("not_an_access_token")
        return claims

    async def _record_rejection(self, reason: str) -> None:
        log.info("token rejected: %s", reason)
        if self._audit is None:
            return
        try:
            await asyncio.to_thread(
                self._audit.record_decision,
                str(uuid.uuid4()),
                Identity(sub=None, client_id=None),
                None,
                None,
                "deny",
                f"invalid_token:{reason}",
            )
        except AuditError:
            log.error("could not audit a token rejection; the request is denied regardless")


def identity_from(access: AccessToken) -> Identity:
    """The audit identity for a validated token: the person and the agent."""
    claims = access.claims or {}
    return Identity(
        sub=access.subject,
        client_id=access.client_id,
        jti=claims.get("jti"),
        scopes=tuple(access.scopes),
    )
