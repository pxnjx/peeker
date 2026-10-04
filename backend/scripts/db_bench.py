"""Write/read benchmark on a private copy of the live database.

Answers three questions without touching the running backend's file:
  1. How expensive is a small commit with synchronous=FULL (the SQLite default the
     app inherits) versus synchronous=NORMAL, which WAL mode is designed for?
  2. What does an un-truncated WAL cost a reader?
  3. Do the hot dashboard queries use an index, or a temp-table sort?

Run:  .venv/Scripts/python.exe scripts/db_bench.py
"""
from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import statistics
import tempfile
import time

LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "peeker.db")
TMP = os.path.join(tempfile.gettempdir(), "peeker_bench.db")

HOT_QUERIES = [
    ("reviews newest 300 (all businesses)",
     "SELECT * FROM reviews ORDER BY COALESCE(review_time, first_seen_at) DESC, id DESC LIMIT 300;"),
    ("reviews newest 300 (one business)",
     "SELECT * FROM reviews WHERE business_id = 1 "
     "ORDER BY COALESCE(review_time, first_seen_at) DESC, id DESC LIMIT 300;"),
    ("latest snapshot per business",
     "SELECT business_id, MAX(id) FROM rating_snapshots GROUP BY business_id;"),
    ("open alerts newest first",
     "SELECT * FROM alerts WHERE seen = 0 ORDER BY id DESC;"),
    ("business status counts",
     "SELECT status, COUNT(*) FROM businesses GROUP BY status;"),
    ("due businesses (scheduler, every 15s)",
     "SELECT id FROM businesses WHERE status IN ('idle','backoff') AND next_due_at <= '2026-09-28';"),
    ("pending performance rows (rename auto-attach)",
     "SELECT * FROM performance_rows WHERE business_id IS NULL AND LOWER(TRIM(source_name)) = 'x';"),
]


def fresh_copy() -> None:
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            os.remove(TMP + suffix)
    # backup() is the safe way to snapshot a database another process is writing to.
    src = sqlite3.connect(LIVE)
    dst = sqlite3.connect(TMP)
    src.backup(dst)
    dst.close()
    src.close()


def timed(label: str, fn) -> float:
    started = time.perf_counter()
    fn()
    elapsed = (time.perf_counter() - started) * 1000
    print(f"  {label:34s} {elapsed:8.2f} ms")
    return elapsed


def write_cost(synchronous: int) -> None:
    """Time 40 single-row commits (one per scrape: a snapshot + a review), the app's pattern."""
    conn = sqlite3.connect(TMP)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(f"PRAGMA synchronous={synchronous};")
    conn.execute("CREATE TABLE IF NOT EXISTS bench (id INTEGER PRIMARY KEY, payload TEXT);")
    conn.commit()
    started = time.perf_counter()
    for i in range(40):
        conn.execute("INSERT INTO bench (payload) VALUES (?);", (f"row-{i}-{'x' * 200}",))
        conn.commit()
    elapsed = (time.perf_counter() - started) * 1000
    print(f"  synchronous={synchronous} 40 commits:  {elapsed:8.2f} ms  "
          f"({elapsed / 40:.2f} ms per commit)")
    conn.execute("DELETE FROM bench;")
    conn.commit()
    conn.close()


def read_cost() -> None:
    conn = sqlite3.connect(TMP)
    conn.execute("PRAGMA journal_mode=WAL;")
    print(f"  WAL on disk: {os.path.getsize(TMP + '-wal') if os.path.exists(TMP + '-wal') else 0} bytes")

    def run_all() -> None:
        for _, sql in HOT_QUERIES:
            conn.execute(sql).fetchall()

    times = [statistics.median([_once(conn, sql) for _ in range(5)]) for _, sql in HOT_QUERIES]
    for (label, _), elapsed in zip(HOT_QUERIES, times, strict=True):
        print(f"  {label:52s} {elapsed:7.3f} ms")
    print(f"  all seven, back to back: {sum(times):7.3f} ms")

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.execute("PRAGMA optimize;")
    conn.close()


def _once(conn: sqlite3.Connection, sql: str) -> float:
    started = time.perf_counter()
    conn.execute(sql).fetchall()
    return (time.perf_counter() - started) * 1000


def plans() -> None:
    conn = sqlite3.connect(TMP)
    for label, sql in HOT_QUERIES:
        print(f"\n  [{label}]")
        for row in conn.execute("EXPLAIN QUERY PLAN " + sql):
            print(f"     {row[3]}")
    conn.close()


print(f"copying {LIVE} -> {TMP} (live file untouched)")
fresh_copy()

print("\n1. commit cost (this is what every scrape pays, and what makes writes feel slow)")
write_cost(2)  # FULL: the SQLite default the app currently inherits
write_cost(1)  # NORMAL: the value WAL mode is documented to use
write_cost(2)
write_cost(1)

print("\n2. read cost of the seven hot dashboard queries")
read_cost()

print("\n3. query plans")
plans()

size = os.path.getsize(LIVE)
wal = os.path.getsize(LIVE + "-wal") if os.path.exists(LIVE + "-wal") else 0
print(f"\nlive file: db={size} bytes  wal={wal} bytes  ratio={wal / max(size, 1):.1f}x")
shutil.rmtree(os.path.dirname(TMP), ignore_errors=True)
