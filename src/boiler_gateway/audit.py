"""Tamper-evident audit store (ADR 0007).

Every call gets a `decision` record, committed before anything else happens.
Calls that reach the device also get an `outcome` record afterwards, linked by
request ID. Records are insert-only and chained: each one stores the SHA-256
of its own content plus the previous record's hash, so editing or removing a
record breaks the chain from that point on.

The chain detects tampering; it does not prevent it. Someone who can write
the file can rebuild the chain, and removing the newest records leaves no gap.
Both are caught by comparing against an anchor (a `seq` and `hash` exported
off the box earlier), which `verify()` accepts.

Records never hold tokens or secrets (P6). The token's `jti` is kept for
correlation instead.

Command line:
    python -m boiler_gateway.audit verify --db data/audit.sqlite [--anchor-seq N --anchor-hash H]
    python -m boiler_gateway.audit head --db data/audit.sqlite
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

GENESIS = "0" * 64

Decision = Literal["allow", "deny", "needs_approval"]
Result = Literal["ok", "confirmed", "unconfirmed", "failed", "error"]

# Argument names that suggest a credential. A tool should never take one, so
# recording such a call is refused rather than risk storing a secret (P6, P7).
_SECRET_KEY = re.compile(
    r"(token|secret|password|passwd|psk|api[_-]?key|authorization)", re.IGNORECASE
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq         INTEGER PRIMARY KEY,
    ts          TEXT    NOT NULL,
    request_id  TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('decision', 'outcome')),
    sub         TEXT,
    client_id   TEXT,
    jti         TEXT,
    scopes      TEXT,
    tool        TEXT,
    arguments   TEXT,
    decision    TEXT,
    reason      TEXT,
    result      TEXT,
    latency_ms  INTEGER,
    prev_hash   TEXT    NOT NULL,
    hash        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_request ON audit (request_id);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit records are append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit records are append-only'); END;
"""

_HASHED_FIELDS = (
    "seq",
    "ts",
    "request_id",
    "kind",
    "sub",
    "client_id",
    "jti",
    "scopes",
    "tool",
    "arguments",
    "decision",
    "reason",
    "result",
    "latency_ms",
    "prev_hash",
)


class AuditError(Exception):
    """The record could not be written. Callers must deny the call (P5, P7)."""


@dataclass(frozen=True)
class Identity:
    """Who is asking: the person and the agent acting for them (ADR 0004)."""

    sub: str | None
    client_id: str | None
    jti: str | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    problem: str | None = None


@dataclass
class _Head:
    seq: int = 0
    hash: str = GENESIS


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _record_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical({k: row[k] for k in _HASHED_FIELDS}).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class AuditLog:
    """Single-writer, insert-only audit store. Thread-safe; use from async code via to_thread."""

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self._path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # Writing

    def record_decision(
        self,
        request_id: str,
        identity: Identity,
        tool: str | None,
        arguments: dict[str, Any] | None,
        decision: Decision,
        reason: str | None = None,
    ) -> int:
        """Commit the policy decision. Returns its seq. Raises AuditError on any failure."""
        self._reject_secret_like(arguments)
        return self._append(
            request_id=request_id,
            kind="decision",
            sub=identity.sub,
            client_id=identity.client_id,
            jti=identity.jti,
            scopes=" ".join(identity.scopes) or None,
            tool=tool,
            arguments=_canonical(arguments) if arguments is not None else None,
            decision=decision,
            reason=reason,
            result=None,
            latency_ms=None,
        )

    def record_outcome(
        self,
        request_id: str,
        result: Result,
        latency_ms: int,
        reason: str | None = None,
    ) -> int:
        """Commit what actually happened. Requires an earlier `allow` decision for the request."""
        with self._lock:
            row = self._db.execute(
                "SELECT tool, sub, client_id, jti, decision FROM audit "
                "WHERE request_id = ? AND kind = 'decision' ORDER BY seq DESC LIMIT 1",
                (request_id,),
            ).fetchone()
        if row is None or row["decision"] != "allow":
            raise AuditError(f"no allow decision recorded for request {request_id}")
        return self._append(
            request_id=request_id,
            kind="outcome",
            sub=row["sub"],
            client_id=row["client_id"],
            jti=row["jti"],
            scopes=None,
            tool=row["tool"],
            arguments=None,
            decision=None,
            reason=reason,
            result=result,
            latency_ms=latency_ms,
        )

    def _append(self, **fields: Any) -> int:
        try:
            with self._lock:
                self._db.execute("BEGIN IMMEDIATE")
                try:
                    last = self._db.execute(
                        "SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1"
                    ).fetchone()
                    head = _Head(last["seq"], last["hash"]) if last else _Head()
                    row = {"seq": head.seq + 1, "ts": _now(), "prev_hash": head.hash, **fields}
                    row["hash"] = _record_hash(row)
                    cols = ", ".join(row)
                    marks = ", ".join("?" for _ in row)
                    self._db.execute(
                        f"INSERT INTO audit ({cols}) VALUES ({marks})", tuple(row.values())
                    )
                    self._db.execute("COMMIT")
                except BaseException:
                    self._db.execute("ROLLBACK")
                    raise
                return row["seq"]
        except AuditError:
            raise
        except Exception as exc:  # any storage failure means the call must be denied
            raise AuditError(f"audit write failed: {exc.__class__.__name__}") from exc

    @staticmethod
    def _reject_secret_like(arguments: dict[str, Any] | None) -> None:
        if not arguments:
            return
        for key in arguments:
            if _SECRET_KEY.search(str(key)):
                raise AuditError(
                    f"refusing to record argument that looks like a credential: {key!r}"
                )

    # Reading

    def head(self) -> tuple[int, str]:
        """The latest (seq, hash), for exporting off the box as an anchor."""
        with self._lock:
            last = self._db.execute(
                "SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return (last["seq"], last["hash"]) if last else (0, GENESIS)

    def verify(self, anchor: tuple[int, str] | None = None) -> VerifyResult:
        """Walk the chain from the start. Optionally check an earlier exported anchor."""
        expected_prev = GENESIS
        expected_seq = 1
        checked = 0
        anchor_seen = anchor is None
        with self._lock:
            rows = self._db.execute("SELECT * FROM audit ORDER BY seq").fetchall()
        for r in rows:
            row = dict(r)
            if row["seq"] != expected_seq:
                return VerifyResult(
                    False, checked, expected_seq, "missing record (gap in sequence)"
                )
            if row["prev_hash"] != expected_prev:
                return VerifyResult(False, checked, row["seq"], "chain broken (prev_hash mismatch)")
            if _record_hash(row) != row["hash"]:
                return VerifyResult(False, checked, row["seq"], "record altered (hash mismatch)")
            if anchor and row["seq"] == anchor[0]:
                if row["hash"] != anchor[1]:
                    return VerifyResult(
                        False, checked, row["seq"], "does not match exported anchor"
                    )
                anchor_seen = True
            expected_prev = row["hash"]
            expected_seq += 1
            checked += 1
        if not anchor_seen:
            return VerifyResult(False, checked, anchor[0], "anchor record missing (log truncated)")
        return VerifyResult(True, checked)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m boiler_gateway.audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="check the hash chain")
    v.add_argument("--db", required=True)
    v.add_argument("--anchor-seq", type=int)
    v.add_argument("--anchor-hash")
    h = sub.add_parser("head", help="print the latest seq and hash (to export as an anchor)")
    h.add_argument("--db", required=True)
    args = ap.parse_args(argv)

    if not Path(args.db).exists():
        print(f"no audit database at {args.db}", file=sys.stderr)
        return 2
    log = AuditLog(args.db)
    try:
        if args.cmd == "head":
            seq, digest = log.head()
            print(f"{seq} {digest}")
            return 0
        anchor = None
        if args.anchor_seq is not None or args.anchor_hash:
            if args.anchor_seq is None or not args.anchor_hash:
                ap.error("--anchor-seq and --anchor-hash go together")
            anchor = (args.anchor_seq, args.anchor_hash)
        res = log.verify(anchor)
        if res.ok:
            print(f"OK: {res.checked} records, chain intact")
            return 0
        print(
            f"FAIL at seq {res.first_bad_seq}: {res.problem} ({res.checked} records good before it)"
        )
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(_main())
