"""Read-only database health probe: schema, indexes, row counts, WAL state, query plans.

Run:  .venv/Scripts/python.exe scripts/db_health.py [path-to-db]
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import time

DEFAULT_DB = str(pathlib.Path(__file__).resolve().parent.parent / "data" / "peeker.db")
db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB

conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row


def show(title: str) -> None:
    print(f"\n--- {title} ---")


show("pragmas")
for pragma in (
    "journal_mode",
    "synchronous",
    "page_size",
    "page_count",
    "freelist_count",
    "cache_size",
    "temp_store",
    "busy_timeout",
    "mmap_size",
):
    print(f"{pragma} = {conn.execute('PRAGMA ' + pragma + ';').fetchone()[0]}")

show("wal checkpoint state (negative busy_timeout: fail fast if a reader blocks it)")
print(conn.execute("PRAGMA wal_checkpoint(PASSIVE);").fetchone())

show("compile options of interest")
opts = {r[0] for r in conn.execute("PRAGMA compile_options;")}
print({k: (k in opts) for k in ("THREADSAFE=1", "ENABLE_FTS3", "SQLITE_ENABLE_MATH_FUNCTIONS")})

show("tables / row counts")
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")]
for table in tables:
    count = conn.execute(f'SELECT COUNT(*) FROM "{table}";').fetchone()[0]
    print(f"{table:24s} {count}")

show("indexes")
indexes = conn.execute(
    "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' ORDER BY tbl_name, name;"
).fetchall()
for row in indexes:
    print(f"{row['tbl_name']:20s} {row['name']:40s} {row['sql']}")
indexed_cols: dict[str, set[str]] = {}
for row in conn.execute("PRAGMA index_list('reviews');"):
    print("reviews index:", dict(row))

show("columns per table")
for table in tables:
    cols = [c[1] + ("" if c[2] else "?") for c in conn.execute(f'PRAGMA table_info("{table}");')]
    print(f"{table}: {', '.join(cols)}")

show("largest tables by pages")
try:
    conn.execute("CREATE TEMP TABLE dbstat AS SELECT * FROM dbstat;")
    for row in conn.execute(
        "SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC LIMIT 12;"
    ):
        print(f"{row[0]:24s} {row[1]}")
except sqlite3.OperationalError as exc:
    print("dbstat unavailable:", exc)

show("review text volume")
row = conn.execute(
    "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(text)),0) AS bytes, COALESCE(AVG(LENGTH(text)),0) AS avg "
    "FROM reviews;"
).fetchone()
print(dict(row))


def timed(label: str, sql: str, params: tuple = ()) -> float:
    started = time.perf_counter()
    rows = conn.execute(sql, params).fetchall()
    elapsed = (time.perf_counter() - started) * 1000
    print(f"{label:46s} {elapsed:8.2f} ms  rows={len(rows)}")
    return elapsed


show("query timings (cold, first execution)")
QUERIES = [
    ("businesses list (dashboard)", "SELECT * FROM businesses ORDER BY name;"),
    ("latest snapshot per business (correlated)",
     "SELECT b.id, (SELECT MAX(captured_at) FROM performance_rows p WHERE p.business_id = b.id) "
     "FROM businesses b;"),
    ("performance_rows latest 200", "SELECT * FROM performance_rows ORDER BY captured_at DESC LIMIT 200;"),
    ("reviews newest 100", "SELECT * FROM reviews ORDER BY published_at DESC LIMIT 100;"),
    ("reviews per business counts",
     "SELECT business_id, COUNT(*) FROM reviews GROUP BY business_id;"),
    ("reviews text LIKE search", "SELECT id FROM reviews WHERE text LIKE '%bagus%';"),
    ("alerts open", "SELECT * FROM alerts WHERE seen = 0 ORDER BY created_at DESC;"),
    ("scrape_jobs recent", "SELECT * FROM scrape_jobs ORDER BY id DESC LIMIT 50;"),
]
for label, sql in QUERIES:
    try:
        timed(label, sql)
    except sqlite3.Error as exc:
        print(f"{label:46s} ERROR {exc}")

show("query plans")
for label, sql in QUERIES[:6]:
    try:
        plan = conn.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
        print(f"[{label}]")
        for p in plan:
            print("   ", p[3])
    except sqlite3.Error as exc:
        print(f"[{label}] ERROR {exc}")

show("freshness")
print(json.dumps(
    {
        "reviews max published_at": conn.execute("SELECT MAX(published_at) FROM reviews;").fetchone()[0],
        "performance max captured_at": conn.execute(
            "SELECT MAX(captured_at) FROM performance_rows;"
        ).fetchone()[0],
        "businesses": conn.execute("SELECT COUNT(*) FROM businesses;").fetchone()[0],
    },
    indent=2,
))
conn.close()
