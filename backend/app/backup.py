"""Database backup / restore for the Settings page (Kwerry /api/backup pattern).

SQLite only: checkpoint the WAL so the main file is complete, then copy it.
Restore validates the SQLite header, keeps a timestamped safety copy of the
live file, swaps the upload over it, and drops stale -wal/-shm files.

Danger: restore REPLACES the live database. The caller must dispose the
engine (or restart the process) before copying, and re-init afterwards —
SQLAlchemy pools hold open file handles otherwise.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import os
import shutil
import sqlite3

from fastapi import HTTPException


def database_path(database_url: str) -> str:
    """Filesystem path of the SQLite file, or '' when not a file-backed SQLite URL."""
    if "sqlite" not in database_url:
        return ""
    path = database_url.split("///", 1)[-1]
    return os.path.abspath(path) if path and path != ":memory:" else ""


def checkpoint(db_path: str) -> None:
    """Fold the WAL back into the main file (best-effort, like Kwerry)."""
    try:
        con = sqlite3.connect(db_path, timeout=8)
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            con.commit()
        finally:
            con.close()
    except Exception:
        pass  # busy / locked: the copy below still carries the committed pages


def is_sqlite_file(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(15) == b"SQLite format 3"
    except OSError:
        return False


def backup_database(db_path: str, dest_path: str) -> str:
    if not db_path or not os.path.exists(db_path):
        raise HTTPException(status_code=503, detail="No database file to back up.")
    checkpoint(db_path)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        shutil.copyfile(db_path, dest_path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write backup: {exc}") from exc
    return dest_path


def restore_database(db_path: str, src_path: str) -> str:
    """Swap an uploaded .db over the live file. Returns the safety-copy path."""
    if not db_path:
        raise HTTPException(status_code=503, detail="Database backup/restore is SQLite-only.")
    if not os.path.exists(src_path):
        raise HTTPException(status_code=400, detail="Backup file not found.")
    if os.path.getsize(src_path) < 100:
        raise HTTPException(status_code=400, detail="Backup file looks empty or invalid.")
    if not is_sqlite_file(src_path):
        raise HTTPException(status_code=400, detail="File is not a valid SQLite database.")
    checkpoint(db_path)
    stamp = dt.datetime.now(dt.UTC).isoformat().replace(":", "-").replace(".", "-")
    safety = f"{db_path}.before-restore-{stamp}"
    try:
        if os.path.exists(db_path):
            shutil.copyfile(db_path, safety)
        shutil.copyfile(src_path, db_path)
        for suffix in ("-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.remove(db_path + suffix)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not restore database: {exc}") from exc
    return safety
