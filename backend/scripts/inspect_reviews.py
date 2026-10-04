"""Quick review-table probe against the local SQLite file.

Run:  .venv/Scripts/python.exe scripts/inspect_reviews.py
"""
from __future__ import annotations

import pathlib
import sqlite3

DEFAULT_DB = pathlib.Path(__file__).resolve().parent.parent / "data" / "peeker.db"

c = sqlite3.connect(DEFAULT_DB)
rows = c.execute(
    "select id, length(text), rating, substr(text,1,100), author from reviews order by id desc limit 25"
).fetchall()
print("id|len|rating|text_start|author")
for r in rows:
    print("|".join(str(x) for x in r))
print("---")
print("total:", c.execute("select count(*) from reviews").fetchone()[0])
print("empty text:", c.execute("select count(*) from reviews where trim(text)=''").fetchone()[0])
print("short text <30:", c.execute("select count(*) from reviews where length(trim(text))<30").fetchone()[0])
print(
    "text with ellipsis-ish:",
    c.execute(
        "select count(*) from reviews where text like '%…%' or text like '%…' or text like '%More'"
    ).fetchone()[0],
)
print("--- rating distribution ---")
for r in c.execute("select rating, count(*) from reviews group by rating order by rating"):
    print(r)
print("--- per business ---")
for r in c.execute(
    "select b.name, count(r.id), sum(case when trim(r.text)='' then 1 else 0 end) as empty_t "
    "from business b left join reviews r on r.business_id=b.id group by b.id"
):
    print(r)
