"""The write path (ADR 0008), exercised as an attacker or a faulty boiler would."""

import asyncio
import json
import sqlite3
import time

import pytest
from mcp_types import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient
from tokens import ISSUER, RESOURCE, FakeAuthServer, token

from boiler_gateway import policy
from boiler_gateway.audit import AuditError, AuditLog
from boiler_gateway.auth import JwksKeys
from boiler_gateway.config import Settings
from boiler_gateway.device import CommandRefused, DeviceSnapshot, Reading

TOOL = "set_hot_water_tank_setpoint"
RW = "boiler:read boiler:write"


class FakeWriteDevice:
    """A boiler that confirms, ignores, or can't receive a command."""

    def __init__(self, behaviour="confirm", delay=0.05, connected=True, setpoint=54.0):
        self.behaviour = behaviour
        self.delay = delay
        self.connected = connected
        self.commands = []
        now = time.time()
        self.readings = {
            "navien_dhw_set_temp": Reading("navien_dhw_set_temp", "", setpoint, "°C", now),
            "navien_operating_state": Reading("navien_operating_state", "", "Standby", "", now),
        }

    async def start(self):
        pass

    async def stop(self):
        pass

    def snapshot(self):
        return DeviceSnapshot(self.connected, dict(self.readings), time.time(), time.time())

    def set_number(self, object_id, value):
        if self.behaviour == "refuse":
            raise CommandRefused("device not connected")
        self.commands.append((object_id, value))
        if self.behaviour == "confirm":
            asyncio.get_running_loop().call_later(self.delay, self._report, value)

    def _report(self, value):
        self.readings["navien_dhw_set_temp"] = Reading(
            "navien_dhw_set_temp", "", value, "°C", time.time()
        )

    async def wait_for_value(self, object_id, expected, timeout, tolerance=0.01):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.readings.get(object_id)
            if r and abs(float(r.value) - float(expected)) <= tolerance:
                return r
            await asyncio.sleep(0.01)
        return None


def settings(writes=True):
    return Settings(
        _env_file=None,
        gateway_issuer=ISSUER,
        gateway_resource_url=RESOURCE,
        gateway_allowed_hosts=["testserver"],
        gateway_writes_enabled=writes,
        esphome_host="192.0.2.10",
        esphome_noise_psk="dGVzdA==",
    )


@pytest.fixture(autouse=True)
def short_readback(monkeypatch):
    monkeypatch.setattr(policy, "READ_BACK_TIMEOUT_SECONDS", 0.3)


@pytest.fixture
def make(tmp_path):
    from boiler_gateway.server import build_app

    clients = []

    def _make(device=None, writes=True, db="audit.sqlite"):
        device = device or FakeWriteDevice()
        audit = AuditLog(tmp_path / db)
        app = build_app(
            settings(writes), device, audit, JwksKeys(ISSUER, 300, FakeAuthServer().fetch)
        )
        client = TestClient(app)
        client.__enter__()
        clients.append((client, audit))
        return client, audit, device

    yield _make
    for client, audit in clients:
        client.__exit__(None, None, None)
        audit.close()


def call(client, args=None, tok=None, method="tools/call", tool=TOOL):
    meta = {
        "io.modelcontextprotocol/protocolVersion": LATEST_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    params = {"_meta": meta}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
        "Mcp-Method": method,
        "Authorization": f"Bearer {tok or token(scope=RW)}",
    }
    if method == "tools/call":
        params.update({"name": tool, "arguments": args or {}})
        headers["Mcp-Name"] = tool
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return client.post("/mcp", headers=headers, content=json.dumps(body))


def result_of(r):
    res = r.json()["result"]
    if res.get("isError"):
        return {"error": res["content"][0]["text"]}
    return res.get("structuredContent") or json.loads(res["content"][0]["text"])


def rows(audit):
    db = sqlite3.connect(audit._path)
    return db.execute(
        "SELECT kind, decision, reason, tool, arguments, result FROM audit ORDER BY seq"
    ).fetchall()


def test_write_tool_is_hidden_when_writes_are_disabled(make):
    client, audit, device = make(writes=False)
    tools = call(client, method="tools/list").json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["get_boiler_status"]
    call(client, {"celsius": 55})
    assert device.commands == []
    assert rows(audit)[-1][:3] == ("decision", "deny", "unknown_tool")


def test_write_tool_is_listed_when_enabled(make):
    client, _, _ = make()
    tools = {t["name"]: t for t in call(client, method="tools/list").json()["result"]["tools"]}
    assert TOOL in tools
    assert tools[TOOL]["annotations"]["readOnlyHint"] is False


def test_read_only_token_gets_step_up_challenge(make):
    client, audit, device = make()
    r = call(client, {"celsius": 55}, tok=token(scope="boiler:read"))
    assert r.status_code == 403
    assert 'scope="boiler:write"' in r.headers["www-authenticate"]
    assert device.commands == []
    assert rows(audit)[-1][1:3] == ("deny", "insufficient_scope")


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (60.5, "out_of_bounds"),
        (39.5, "out_of_bounds"),
        (82, "out_of_bounds"),
        (54.3, "not_a_valid_step"),
    ],
)
def test_values_outside_policy_never_reach_the_device(make, value, reason):
    client, audit, device = make()
    out = result_of(call(client, {"celsius": value}))
    assert "Refused" in out["error"]
    assert device.commands == []
    assert rows(audit)[-1][1:3] == ("deny", reason)


def test_confirmed_write_with_audit_before_and_after(make):
    client, audit, device = make()
    out = result_of(call(client, {"celsius": 55}))
    assert out["result"] == "confirmed" and out["changed"] is True
    assert (out["previous_c"], out["reported_c"]) == (54.0, 55)
    assert device.commands == [("navien_dhw_setpoint", 55)]
    log = rows(audit)
    decision = next(r for r in log if r[2] == "policy_ok")
    assert decision[:2] == ("decision", "allow") and json.loads(decision[4]) == {"celsius": 55}
    assert log[-1][0] == "outcome" and log[-1][5] == "confirmed"
    assert log.index(decision) < len(log) - 1  # decision committed before the outcome
    assert audit.verify().ok


def test_same_value_sends_nothing_and_does_not_use_the_rate_limit(make):
    client, audit, device = make()
    out = result_of(call(client, {"celsius": 54}))
    assert out["result"] == "confirmed" and out["changed"] is False
    assert device.commands == []
    assert rows(audit)[-2][1:3] == ("allow", "no_change")
    assert result_of(call(client, {"celsius": 55}))["result"] == "confirmed"  # still allowed


def test_rate_limit_blocks_a_second_write(make):
    client, audit, device = make()
    assert result_of(call(client, {"celsius": 55}))["result"] == "confirmed"
    out = result_of(call(client, {"celsius": 56}))
    assert "Try again in" in out["error"]
    assert device.commands == [("navien_dhw_setpoint", 55)]
    assert rows(audit)[-1][1:3] == ("deny", "rate_limited")


def test_rate_limit_survives_a_restart(make):
    client, _, _ = make(db="shared.sqlite")
    assert result_of(call(client, {"celsius": 55}))["result"] == "confirmed"
    client2, _, device2 = make(db="shared.sqlite")
    out = result_of(call(client2, {"celsius": 56}))
    assert "Try again in" in out["error"]
    assert device2.commands == []


def test_unconfirmed_write_is_reported_honestly_and_not_retried(make):
    client, audit, device = make(FakeWriteDevice(behaviour="ignore"))
    out = result_of(call(client, {"celsius": 55}))
    assert out["result"] == "unconfirmed" and out["changed"] is False
    assert out["reported_c"] == 54.0
    assert device.commands == [("navien_dhw_setpoint", 55)]  # sent once, never retried
    assert rows(audit)[-1][5] == "unconfirmed"


def test_failed_send_is_reported(make):
    client, audit, device = make(FakeWriteDevice(behaviour="refuse"))
    out = result_of(call(client, {"celsius": 55}))
    assert out["result"] == "failed"
    assert device.commands == []
    assert rows(audit)[-1][5] == "failed"


def test_disconnected_device_refuses_writes(make):
    client, audit, device = make(FakeWriteDevice(connected=False))
    out = result_of(call(client, {"celsius": 55}))
    assert "isn't connected" in out["error"]
    assert device.commands == []
    assert rows(audit)[-1][1:3] == ("deny", "device_disconnected")


def test_audit_failure_before_the_command_means_no_command(make, monkeypatch):
    client, audit, device = make()
    original = audit.record_decision

    def failing(request_id, who, tool, args, decision, reason=None):
        if reason == "policy_ok":
            raise AuditError("disk full")
        return original(request_id, who, tool, args, decision, reason)

    monkeypatch.setattr(audit, "record_decision", failing)
    r = call(client, {"celsius": 55})
    assert device.commands == []
    assert "confirmed" not in r.text
