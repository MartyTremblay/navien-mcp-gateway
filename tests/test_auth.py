import time

import jwt
import pytest
from tokens import (
    ISSUER,
    KID,
    OTHER_KEY,
    RESOURCE,
    SIGNING_KEY,
    FakeAuthServer,
    claims,
    jwk_of,
    token,
)

from boiler_gateway.audit import AuditLog
from boiler_gateway.auth import GatewayTokenVerifier, JwksKeys, identity_from
from boiler_gateway.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        gateway_issuer=ISSUER,
        gateway_resource_url=RESOURCE,
        esphome_host="192.0.2.10",
        esphome_noise_psk="dGVzdA==",
    )


@pytest.fixture
def audit(tmp_path):
    lg = AuditLog(tmp_path / "audit.sqlite")
    yield lg
    lg.close()


def verifier(settings, audit=None, server=None):
    server = server or FakeAuthServer()
    return GatewayTokenVerifier(settings, JwksKeys(ISSUER, 300, server.fetch), audit), server


def last_reason(audit):
    import sqlite3

    db = sqlite3.connect(audit._path)
    return db.execute("SELECT decision, reason FROM audit ORDER BY seq DESC LIMIT 1").fetchone()


async def test_valid_token_is_accepted(settings):
    v, _ = verifier(settings)
    access = await v.verify_token(token())
    assert access is not None
    assert access.client_id == "claude-code"
    assert access.subject == "person-1"
    assert access.scopes == ["boiler:read"]
    assert access.resource == RESOURCE
    ident = identity_from(access)
    assert (ident.sub, ident.client_id, ident.jti) == ("person-1", "claude-code", "jti-1")


@pytest.mark.parametrize(
    ("tok_kwargs", "reason"),
    [
        ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 4000}, "expired"),
        ({"aud": "https://other.example.org/mcp"}, "wrong_audience"),
        ({"aud": [RESOURCE, "account"]}, "audience_not_exclusive"),
        ({"iss": "https://evil.example.org/realms/home"}, "wrong_issuer"),
        ({"key": OTHER_KEY}, "bad_signature"),
        ({"azp": None}, "missing_claim:azp"),
        ({"typ": "ID"}, "not_an_access_token"),
        ({"kid": "rotated-away"}, "unknown_signing_key"),
        ({"kid": None}, "no_key_id"),
    ],
)
async def test_bad_tokens_are_refused_and_audited(settings, audit, tok_kwargs, reason):
    v, _ = verifier(settings, audit)
    assert await v.verify_token(token(**tok_kwargs)) is None
    assert last_reason(audit) == ("deny", f"invalid_token:{reason}")


async def test_unsigned_token_is_refused(settings, audit):
    v, _ = verifier(settings, audit)
    unsigned = jwt.encode(claims(), None, algorithm="none", headers={"kid": KID})
    assert await v.verify_token(unsigned) is None
    assert last_reason(audit) == ("deny", "invalid_token:algorithm_not_allowed")


async def test_algorithm_confusion_is_refused(settings, audit):
    # HS256 "signed" with the public key: a classic confusion attack.
    pem = jwk_of(SIGNING_KEY)["n"].encode()
    forged = jwt.encode(claims(), pem, algorithm="HS256", headers={"kid": KID})
    v, _ = verifier(settings, audit)
    assert await v.verify_token(forged) is None
    assert last_reason(audit) == ("deny", "invalid_token:algorithm_not_allowed")


async def test_garbage_is_refused(settings, audit):
    v, _ = verifier(settings, audit)
    assert await v.verify_token("not-a-jwt") is None
    assert last_reason(audit) == ("deny", "invalid_token:malformed")


async def test_keys_unreachable_fails_closed(settings, audit):
    v, _ = verifier(settings, audit, FakeAuthServer(fail=True))
    assert await v.verify_token(token()) is None
    assert last_reason(audit) == ("deny", "invalid_token:signing_keys_unavailable")


async def test_discovery_issuer_mismatch_fails_closed(settings, audit):
    v, _ = verifier(settings, audit, FakeAuthServer(issuer="https://evil.example.org/realms/home"))
    assert await v.verify_token(token()) is None
    assert last_reason(audit) == ("deny", "invalid_token:signing_keys_unavailable")


async def test_keys_are_cached(settings):
    v, server = verifier(settings)
    await v.verify_token(token())
    calls = server.calls
    await v.verify_token(token())
    assert server.calls == calls  # no refetch within the cache period


async def test_symmetric_algorithms_cannot_be_configured(settings):
    settings.gateway_token_algorithms = ["HS256"]
    with pytest.raises(ValueError):
        verifier(settings)


async def test_token_never_reaches_the_audit_store(settings, audit):
    v, _ = verifier(settings, audit)
    bad = token(aud="https://other.example.org/mcp")
    await v.verify_token(bad)
    audit.close()
    raw = b"".join(p.read_bytes() for p in audit._path.parent.iterdir())
    assert bad.encode() not in raw
    assert bad.split(".")[2].encode() not in raw  # not even the signature part
