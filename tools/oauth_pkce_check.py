#!/usr/bin/env python3
"""Get an access token with authorization code + PKCE and report its claims.

Checks the authorization server setup that ADR 0004 and ADR 0005 depend on:
the token's audience must be exactly the resource (RFC 8707), the issuer must
match discovery, and the authorization response must carry `iss` (RFC 9207).

The token itself is never printed or stored. Standard library only.

Example:
    python3 tools/oauth_pkce_check.py \\
        --issuer https://auth.lab.example.org/realms/home \\
        --client-id mcp-test-cli \\
        --resource https://boiler.lab.example.org/mcp \\
        --scope boiler:read
"""

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import ssl
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def fetch_json(url: str, ctx: ssl.SSLContext, data: dict | None = None) -> dict:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        sys.exit(f"HTTP {err.code} from {url}: {detail}")


def wait_for_callback(port: int, path: str) -> dict:
    result: dict = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != path:
                self.send_error(404)
                return
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and return to the terminal.")
            done.set()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if not done.wait(timeout=300):
        server.shutdown()
        sys.exit("No callback within 5 minutes.")
    server.shutdown()
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issuer", required=True, help="realm issuer URL, e.g. https://auth.lab.example.org/realms/home")
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--resource", required=True, help="the gateway's canonical MCP URL (RFC 8707)")
    ap.add_argument("--scope", default="boiler:read", help="space-separated scopes to request")
    ap.add_argument("--port", type=int, default=8765, help="loopback port for the redirect URI")
    ap.add_argument("--insecure", action="store_true", help="skip TLS verification (only until the lab certificate exists)")
    args = ap.parse_args()

    ctx = ssl.create_default_context()
    if args.insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        print("WARNING: TLS verification is off.")

    meta = fetch_json(args.issuer.rstrip("/") + "/.well-known/openid-configuration", ctx)
    if meta.get("issuer") != args.issuer.rstrip("/"):
        sys.exit(f"Issuer mismatch: discovery says {meta.get('issuer')!r}")

    redirect_uri = f"http://127.0.0.1:{args.port}/callback"
    verifier = b64url(secrets.token_bytes(32))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    state = b64url(secrets.token_bytes(16))

    auth_url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": args.client_id,
        "redirect_uri": redirect_uri,
        "scope": args.scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": args.resource,
    })
    print("Opening the browser to sign in. If it doesn't open, visit:\n" + auth_url + "\n")
    webbrowser.open(auth_url)
    cb = wait_for_callback(args.port, "/callback")

    if cb.get("state") != state:
        sys.exit("State mismatch: possible CSRF or a stale browser tab.")
    if meta.get("authorization_response_iss_parameter_supported") and cb.get("iss") != meta["issuer"]:
        sys.exit(f"RFC 9207 check failed: iss={cb.get('iss')!r}, expected {meta['issuer']!r}")
    if "error" in cb:
        sys.exit(f"Authorization error: {cb.get('error')}: {cb.get('error_description', '')}")

    tok = fetch_json(meta["token_endpoint"], ctx, {
        "grant_type": "authorization_code",
        "code": cb["code"],
        "redirect_uri": redirect_uri,
        "client_id": args.client_id,
        "code_verifier": verifier,
        "resource": args.resource,
    })
    access = tok.get("access_token", "")
    parts = access.split(".")
    if len(parts) != 3:
        sys.exit("Access token is not a JWT; cannot inspect claims.")
    claims = json.loads(b64url_decode(parts[1]))

    aud = claims.get("aud")
    aud_list = aud if isinstance(aud, list) else [aud]
    report = {
        "iss": claims.get("iss"),
        "aud": aud,
        "azp (client)": claims.get("azp"),
        "sub (person)": claims.get("sub"),
        "preferred_username": claims.get("preferred_username"),
        "scope": claims.get("scope"),
        "lifetime_seconds": claims.get("exp", 0) - claims.get("iat", 0),
    }
    print(json.dumps(report, indent=2))

    checks = {
        "issuer matches discovery": claims.get("iss") == meta["issuer"],
        "aud is exactly the resource": aud_list == [args.resource],
        "requested scopes granted": set(args.scope.split()) <= set((claims.get("scope") or "").split()),
        "lifetime is 5 minutes or less": report["lifetime_seconds"] <= 300,
    }
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
