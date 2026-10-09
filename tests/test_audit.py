import sqlite3
from itertools import pairwise

import pytest

from boiler_gateway.audit import GENESIS, AuditError, AuditLog, Identity, _main

WHO = Identity(sub="person-1", client_id="claude-code", jti="tok-1", scopes=("boiler:read",))


@pytest.fixture
def log(tmp_path):
    lg = AuditLog(tmp_path / "audit.sqlite")
    yield lg
    lg.close()


def raw(log):
    """A second connection, as an attacker with file access would have."""
    return sqlite3.connect(log._path, isolation_level=None)


def fill(log, n=5):
    for i in range(n):
        log.record_decision(f"r{i}", WHO, "get_boiler_status", {"detail": i}, "allow")
        log.record_outcome(f"r{i}", "ok", 12)


def test_records_chain_from_genesis(log):
    fill(log, 2)
    rows = raw(log).execute("SELECT seq, prev_hash, hash FROM audit ORDER BY seq").fetchall()
    assert rows[0][1] == GENESIS
    for prev, cur in pairwise(rows):
        assert cur[1] == prev[2]
    assert log.verify().ok
    assert log.verify().checked == 4


def test_denials_are_recorded(log):
    log.record_decision("r1", WHO, "set_dhw_setpoint", {"celsius": 80}, "deny", "out_of_bounds")
    row = raw(log).execute("SELECT kind, decision, reason, sub, client_id FROM audit").fetchone()
    assert row == ("decision", "deny", "out_of_bounds", "person-1", "claude-code")


def test_outcome_requires_an_allow_decision(log):
    with pytest.raises(AuditError):
        log.record_outcome("never-decided", "ok", 1)
    log.record_decision("r1", WHO, "t", None, "deny", "no_scope")
    with pytest.raises(AuditError):
        log.record_outcome("r1", "ok", 1)


def test_updates_and_deletes_are_blocked(log):
    fill(log, 1)
    db = raw(log)
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE audit SET decision = 'deny' WHERE seq = 1")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM audit WHERE seq = 1")


def test_edit_is_detected_even_if_triggers_are_dropped(log):
    fill(log, 3)
    db = raw(log)
    db.execute("DROP TRIGGER audit_no_update")
    db.execute("UPDATE audit SET decision = 'deny' WHERE seq = 3")
    res = log.verify()
    assert not res.ok and res.first_bad_seq == 3 and "altered" in res.problem


def test_deleted_middle_record_is_detected(log):
    fill(log, 3)
    db = raw(log)
    db.execute("DROP TRIGGER audit_no_delete")
    db.execute("DELETE FROM audit WHERE seq = 2")
    res = log.verify()
    assert not res.ok and res.first_bad_seq == 2


def test_rebuilt_chain_or_truncation_needs_an_anchor(log):
    fill(log, 3)
    anchor = log.head()
    db = raw(log)
    db.execute("DROP TRIGGER audit_no_delete")
    db.execute("DELETE FROM audit WHERE seq > 4")  # remove the newest records
    assert log.verify().ok  # a clean prefix looks intact on its own...
    res = log.verify(anchor)  # ...but not against the exported anchor
    assert not res.ok and "truncated" in res.problem


def test_wrong_anchor_is_detected(log):
    fill(log, 2)
    seq, _ = log.head()
    assert not log.verify((seq, "f" * 64)).ok


def test_credential_like_arguments_are_refused(log):
    with pytest.raises(AuditError):
        log.record_decision("r1", WHO, "t", {"access_token": "x"}, "allow")
    assert log.head() == (0, GENESIS)  # nothing written


def test_storage_failure_raises_audit_error(log):
    log._db.close()
    with pytest.raises(AuditError):
        log.record_decision("r1", WHO, "t", None, "allow")


def test_cli_verify_and_head(log, capsys):
    fill(log, 1)
    db = str(log._path)
    assert _main(["verify", "--db", db]) == 0
    assert "chain intact" in capsys.readouterr().out
    assert _main(["head", "--db", db]) == 0
    seq, digest = capsys.readouterr().out.split()
    assert int(seq) == 2 and len(digest) == 64
    assert _main(["verify", "--db", db, "--anchor-seq", seq, "--anchor-hash", digest]) == 0
