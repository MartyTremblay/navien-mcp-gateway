import json
import sqlite3
import time

import pytest
from mcp_types import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient
from tokens import ISSUER, RESOURCE, FakeAuthServer, token

from boiler_gateway.audit import AuditLog
from boiler_gateway.auth import JwksKeys
from boiler_gateway.config import Settings
from boiler_gateway.device import DeviceSnapshot, Reading
from boiler_gateway.server import build_app


class FakeDevice:
    def __init__(self, connected=True):
        self.connected = connected
        self.started = self.stopped = False
        now = time.time()
        self.readings = {
            "navien_operating_state": Reading("navien_operating_state", "", "Standby", "", now),
            "navien_outlet_temp": Reading("navien_outlet_temp", "", 51.0, "°C", now),
            "navien_error_code": Reading("navien_error_code", "", 0.0, "", now),
            "navien_ip_address": Reading("navien_ip_address", "", "192.0.2.43", "", now),
        }

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def snapshot(self):
        return DeviceSnapshot(self.connected, dict(self.readings), time.time())


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        _env_file=None,
        gateway_issuer=ISSUER,
        gateway_resource_url=RESOURCE,
        gateway_allowed_hosts=["testserver"],
        gateway_allowed_origins=["https://allowed.example.org"],
        esphome_host="192.0.2.10",
        esphome_noise_psk="dGVzdA==",
    )
    audit = AuditLog(tmp_path / "audit.sqlite")
    device = FakeDevice()
    app = build_app(settings, device, audit, JwksKeys(ISSUER, 300, FakeAuthServer().fetch))
    with TestClient(app) as client:
        yield client, audit, device
    audit.close()


def call(client, tool="get_boiler_status", tok=None, method="tools/call", headers=None, name=None):
    params = {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": LATEST_PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    }
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if method == "tools/call":
        params.update({"name": tool, "arguments": {}})
        h["Mcp-Name"] = name or tool
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    h.update(headers or {})
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return client.post("/mcp", headers=h, content=json.dumps(body))


def audit_rows(audit):
    db = sqlite3.connect(audit._path)
    return db.execute(
        "SELECT kind, decision, reason, tool, sub, client_id, result FROM audit"
    ).fetchall()


def test_device_starts_and_stops_with_the_app(tmp_path):
    settings = Settings(
        _env_file=None,
        gateway_issuer=ISSUER,
        gateway_resource_url=RESOURCE,
        esphome_host="192.0.2.10",
        esphome_noise_psk="dGVzdA==",
    )
    audit = AuditLog(tmp_path / "a.sqlite")
    device = FakeDevice()
    with TestClient(
        build_app(settings, device, audit, JwksKeys(ISSUER, 300, FakeAuthServer().fetch))
    ):
        assert device.started
    assert device.stopped
    audit.close()


def test_protected_resource_metadata(env):
    client, _, _ = env
    r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    meta = r.json()
    assert meta["resource"] == RESOURCE
    assert meta["authorization_servers"] == [ISSUER]
    assert meta["scopes_supported"] == ["boiler:read"]


def test_no_token_gets_401_challenge_and_is_audited(env):
    client, audit, _ = env
    r = call(client)
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]
    assert audit_rows(audit)[-1][:3] == ("decision", "deny", "no_token")


def test_valid_call_returns_curated_status_and_is_audited(env):
    client, audit, _ = env
    r = call(client, tok=token())
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    status = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert status["device_connected"] is True
    assert status["values"]["tank_temperature_c"]["value"] == 51.0
    assert status["values"]["error_code"]["value"] == 0  # integer, not 0.0
    assert "192.0.2.43" not in r.text  # diagnostic values are not exposed
    rows = audit_rows(audit)
    assert rows[-2] == (
        "decision",
        "allow",
        None,
        "get_boiler_status",
        "person-1",
        "claude-code",
        None,
    )
    assert rows[-1][0] == "outcome" and rows[-1][6] == "ok"
    assert audit.verify().ok


def test_missing_scope_gets_403_insufficient_scope(env):
    client, audit, _ = env
    r = call(client, tok=token(scope="boiler:write"))
    assert r.status_code == 403
    assert 'error="insufficient_scope"' in r.headers["www-authenticate"]
    assert 'scope="boiler:read"' in r.headers["www-authenticate"]
    assert audit_rows(audit)[-1][1] == "deny"


def test_wrong_audience_is_refused_and_audited(env):
    client, audit, _ = env
    r = call(client, tok=token(aud="https://other.example.org/mcp"))
    assert r.status_code == 401
    assert audit_rows(audit)[-1][2] == "invalid_token:wrong_audience"


def test_unknown_tool_is_denied(env):
    client, audit, _ = env
    r = call(client, tool="set_main_power", tok=token())
    assert "Standby" not in r.text
    assert ("decision", "deny", "unknown_tool") == audit_rows(audit)[-1][:3]


def test_header_body_mismatch_is_rejected(env):
    client, _, _ = env
    # Header claims the status tool; body calls something else.
    r = call(client, tool="set_main_power", name="get_boiler_status", tok=token())
    assert r.status_code == 400
    assert "Standby" not in r.text


def test_bad_origin_is_rejected(env):
    client, _, _ = env
    r = call(client, tok=token(), headers={"Origin": "https://evil.example.org"})
    assert r.status_code == 403


def test_bad_host_is_rejected(env):
    client, _, _ = env
    r = call(client, tok=token(), headers={"Host": "evil.example.org"})
    assert r.status_code in (400, 421)


def test_disconnected_device_is_reported_stale(env):
    client, audit, device = env
    device.connected = False
    r = call(client, tok=token())
    result = r.json()["result"]
    status = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert status["stale"] is True
    assert audit_rows(audit)[-1][6] == "unconfirmed"


def test_tools_list_shows_only_the_read_tool(env):
    client, _, _ = env
    r = call(client, method="tools/list", tok=token())
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["get_boiler_status"]
    assert tools[0]["annotations"]["readOnlyHint"] is True
