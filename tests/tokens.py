"""Test-only signing keys, a fake authorization server and token builders."""

import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://auth.lab.example.org/realms/home"
RESOURCE = "https://boiler.lab.example.org/mcp"
KID = "test-key-1"


def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNING_KEY = rsa_key()
OTHER_KEY = rsa_key()


def jwk_of(private_key, kid=KID):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


class FakeAuthServer:
    def __init__(self, keys=None, fail=False, issuer=ISSUER):
        self.keys = keys if keys is not None else [jwk_of(SIGNING_KEY)]
        self.fail = fail
        self.issuer = issuer
        self.calls = 0

    async def fetch(self, url):
        self.calls += 1
        if self.fail:
            raise OSError("authorization server unreachable")
        if url.endswith("/.well-known/openid-configuration"):
            return {"issuer": self.issuer, "jwks_uri": ISSUER + "/protocol/openid-connect/certs"}
        return {"keys": self.keys}


def claims(**over):
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": RESOURCE,
        "sub": "person-1",
        "azp": "claude-code",
        "scope": "boiler:read",
        "typ": "Bearer",
        "jti": "jti-1",
        "iat": now,
        "exp": now + 300,
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def token(key=SIGNING_KEY, alg="RS256", kid=KID, **over):
    return jwt.encode(claims(**over), key, algorithm=alg, headers={"kid": kid} if kid else None)
