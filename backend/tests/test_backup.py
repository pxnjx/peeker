"""Backup / restore endpoint tests (the Settings page's data tools).

Covers the read path end to end (a signed session downloads a real SQLite
file) and the validation gates on the destructive path. The happy-path restore
is exercised at the library level in test_backup_roundtrip, which is also where
the file swap is safe to assert: hitting POST /api/backup/restore over HTTP
would replace the session's own test database mid-run.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from app.backup import backup_database, database_path, is_sqlite_file, restore_database
from app.main import create_app
from tests.conftest import api_client


async def test_backup_download_returns_a_sqlite_file() -> None:
    app = create_app()
    async with api_client(app) as client:
        resp = await client.get("/api/backup")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    assert "peeker-backup-" in resp.headers.get("content-disposition", "")
    # The 16-byte SQLite magic survives the round trip through the HTTP layer.
    assert resp.content[:15] == b"SQLite format 3"
    assert len(resp.content) > 100


async def test_backup_and_restore_require_a_session() -> None:
    app = create_app()
    async with api_client(app, session=None) as client:
        assert (await client.get("/api/backup")).status_code == 401
        assert (
            await client.post("/api/backup/restore", files={"file": ("x.db", b"junk" * 40)})
        ).status_code == 401


async def test_restore_rejects_a_non_sqlite_upload() -> None:
    """Validation happens before the swap, so a bad upload never touches the live file."""
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post(
            "/api/backup/restore", files={"file": ("not-a-db.db", b"definitely not sqlite" * 10)}
        )
    assert resp.status_code == 400
    assert "SQLite" in resp.json()["detail"]


async def test_restore_rejects_an_empty_upload() -> None:
    app = create_app()
    async with api_client(app) as client:
        resp = await client.post("/api/backup/restore", files={"file": ("empty.db", b"")})
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"]


def test_database_path_resolves_only_file_backed_sqlite() -> None:
    assert database_path("sqlite+aiosqlite:///./data/peeker.db").endswith("peeker.db")
    assert database_path("sqlite+aiosqlite:///:memory:") == ""
    assert database_path("postgresql+asyncpg://host/db") == ""


def _query(path: str, sql: str) -> list[tuple]:
    """Run one statement on a fresh connection.

    Explicit close on purpose: `with sqlite3.connect(...)` only commits, it does
    not close, and Windows refuses to delete a file the process still holds.
    """
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _execute(path: str, sql: str) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(sql)
        con.commit()
    finally:
        con.close()


def test_backup_roundtrip_restores_the_earlier_snapshot() -> None:
    """Snapshot, mutate, restore, and prove the mutation is gone."""
    with tempfile.TemporaryDirectory() as tmp:
        live = os.path.join(tmp, "live.db")
        _execute(live, "CREATE TABLE t (x INTEGER)")
        _execute(live, "INSERT INTO t VALUES (1)")

        dest = os.path.join(tmp, "backup.db")
        backup_database(live, dest)
        assert is_sqlite_file(dest)

        _execute(live, "INSERT INTO t VALUES (2)")
        assert _query(live, "SELECT COUNT(*) FROM t")[0][0] == 2

        safety = restore_database(live, dest)
        assert os.path.exists(safety)  # the pre-restore copy is kept
        assert _query(live, "SELECT COUNT(*) FROM t")[0][0] == 1
        # Stale WAL sidecars are dropped so the next open starts clean.
        assert not os.path.exists(live + "-wal")
        assert not os.path.exists(live + "-shm")
