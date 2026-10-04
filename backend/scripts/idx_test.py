"""Does an expression index actually remove the temp-table sort on the reviews list?

SQLite only uses an expression index when the expression in the query matches the
indexed expression. SQLAlchemy qualifies columns with the table name, so this checks
the qualified form, not just the bare one.

The copy of the live database already carries the indexes the app created on startup,
so the baseline pass drops them first; otherwise "baseline" silently measures the
indexed query and the second CREATE INDEX dies with "index already exists".

Run:  .venv/Scripts/python.exe scripts/idx_test.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time

LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "peeker.db")
COPY = os.path.join(tempfile.gettempdir(), "peeker_idx.db")

# Names of the expression indexes the app creates on startup. They are dropped
# before the baseline pass and rebuilt below, so "baseline" really is unindexed.
RECENCY_INDEXES = ("ix_reviews_business_recency", "ix_reviews_recency")

shutil.copy(LIVE, COPY)
conn = sqlite3.connect(COPY)
# A tiny table so the plan has something to chew on without waiting for real volume.
conn.execute("INSERT INTO reviews (business_id, google_review_id, author, rating, text) "
             "SELECT business_id, google_review_id || '-x' || abs(random() % 100000), author, rating, text "
             "FROM reviews")
conn.execute("INSERT INTO reviews (business_id, google_review_id, author, rating, text) "
             "SELECT business_id, google_review_id || '-y' || abs(random() % 100000), author, rating, text "
             "FROM reviews")
conn.commit()
total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
print(f"fixture rows: {total}")

ORM_SQL = (
    "SELECT reviews.id, reviews.text FROM reviews "
    "ORDER BY COALESCE(reviews.review_time, reviews.first_seen_at) DESC, reviews.id DESC LIMIT 300"
)


def plan(label: str, sql: str = ORM_SQL) -> None:
    print(f"\n[{label}]")
    for row in conn.execute("EXPLAIN QUERY PLAN " + sql):
        print("   ", row[3])
    started = time.perf_counter()
    for _ in range(20):
        conn.execute(sql).fetchall()
    print(f"    20 runs: {(time.perf_counter() - started) * 1000:.1f} ms")


for name in RECENCY_INDEXES:
    conn.execute(f"DROP INDEX IF EXISTS {name}")
plan("baseline (recency indexes dropped)")

conn.execute(
    "CREATE INDEX ix_reviews_recency ON reviews (COALESCE(review_time, first_seen_at) DESC, id DESC)"
)
plan("expression index, bare column names")

conn.execute("CREATE INDEX ix_reviews_business_recency ON reviews "
             "(business_id, COALESCE(review_time, first_seen_at) DESC, id DESC)")
plan("expression index + business filter",
     ORM_SQL.replace("FROM reviews ", "FROM reviews WHERE reviews.business_id = 1 "))

plan("plain table scan count (control)", "SELECT COUNT(*) FROM reviews")

print("\nindex definitions sqlite kept:")
for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND name LIKE 'ix_reviews%'"):
    print(f"   {row[0]}: {row[1]}")
conn.close()
os.remove(COPY)
