"""Declarative base + async session factory."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import cast

from sqlalchemy import String, event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings
from .base import Base  # single shared declarative base (models register on this)

log = logging.getLogger(__name__)

_settings = get_settings()
_SQLITE = "sqlite" in _settings.database_url

# SQLite concurrency: WAL + busy_timeout so scheduler + API + workers can share one file.
# The busy timeout is 8s rather than sqlite3's 5s default: long enough to ride out a worker's
# commit, short enough that a stuck lock surfaces as an error instead of a frozen request.
# (It used to be 30s, which turned every write collision into a half-minute hang.)
engine = create_async_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    connect_args={"check_same_thread": False, "timeout": 8} if _SQLITE else {},
)

# Per-connection profile. The journal settings have to be set on *every* connection:
# `init_db` only ever touches one, and the pool hands the rest out unconfigured.
_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    # WAL is documented to run at NORMAL; FULL (the default this app inherited) fsyncs on
    # every commit. Measured on a copy of the live file: 0.88ms vs 0.13ms per scrape commit,
    # and the gap widens on Windows with antivirus watching the data directory (scripts/db_bench.py).
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=8000",
    "PRAGMA cache_size=-8000",  # 8MB per connection, up from the 2MB default
    "PRAGMA temp_store=MEMORY",
    # SQLite auto-checkpoints but never shrinks the WAL, so a long-lived server leaves it at
    # its high-water mark: the live file sat at 4.1MB against a 196KB database (21x), and
    # every reader pays to walk it. This caps it at 1MB after each checkpoint.
    "PRAGMA journal_size_limit=1048576",
)

if _SQLITE:

    @event.listens_for(engine.sync_engine, "connect")
    def _tune_sqlite(dbapi_connection, _connection_record) -> None:  # pragma: no cover - dialect specific
        for pragma in _SQLITE_PRAGMAS:
            dbapi_connection.execute(pragma)


session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with session_factory() as session:
        yield session



# Hot-path indexes for queries the dashboard runs on every poll. The two review indexes are
# expression indexes: the list sorts by COALESCE(review_time, first_seen_at), which no plain
# column index can serve, so SQLite was building a temp b-tree over the whole table each time.
_QUERY_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_reviews_recency ON reviews "
    "(COALESCE(review_time, first_seen_at) DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS ix_reviews_business_recency ON reviews "
    "(business_id, COALESCE(review_time, first_seen_at) DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS ix_alerts_seen_id ON alerts (seen, id)",
    "CREATE INDEX IF NOT EXISTS ix_businesses_status_due ON businesses (status, next_due_at)",
)


async def _migrate_performance_table(conn: AsyncConnection) -> None:
    """Rebuild ``performance_rows`` once for pending-upload support.

    ``create_all`` never alters existing tables, so databases created earlier keep
    ``business_id NOT NULL`` (and lack ``source_name``). The rebuild preserves rows.
    Idempotent: no-op when the schema is already current.
    """
    from sqlalchemy import Table
    from sqlalchemy.schema import CreateIndex, CreateTable

    from .models import PerformanceRow

    info = await conn.exec_driver_sql("PRAGMA table_info(performance_rows)")
    cols = {row[1]: row for row in info}
    if not cols or not cols["business_id"][3]:  # table absent (just created) or already nullable
        return
    table = cast("Table", PerformanceRow.__table__)
    selects: list[str] = []
    for col in table.columns:
        if col.name in cols:
            selects.append(col.name)
        elif col.nullable:
            selects.append("NULL")
        else:  # new NOT NULL column (source_name) → backfill with a literal
            selects.append("''" if isinstance(col.type, String) else "0")
    await conn.exec_driver_sql("ALTER TABLE performance_rows RENAME TO performance_rows_old")
    await conn.exec_driver_sql(str(CreateTable(table).compile(dialect=engine.dialect)))
    column_list = ", ".join(c.name for c in table.columns)
    await conn.exec_driver_sql(
        f"INSERT INTO performance_rows ({column_list}) SELECT {', '.join(selects)} FROM performance_rows_old"
    )
    await conn.exec_driver_sql("DROP TABLE performance_rows_old")
    for idx in table.indexes:  # indexes were dropped together with performance_rows_old
        await conn.exec_driver_sql(str(CreateIndex(idx).compile(dialect=engine.dialect)))


async def _migrate_business_detail_columns(conn: AsyncConnection) -> None:
    """Add place-profile columns to ``businesses`` for databases created before they existed.

    ``create_all`` never alters existing tables. Idempotent: only missing columns are added.
    """
    info = await conn.exec_driver_sql("PRAGMA table_info(businesses)")
    cols = {row[1] for row in info}
    if not cols:
        return
    for name, ddl in (
        ("address", "ALTER TABLE businesses ADD COLUMN address TEXT"),
        ("phone", "ALTER TABLE businesses ADD COLUMN phone TEXT"),
        ("website", "ALTER TABLE businesses ADD COLUMN website TEXT"),
        ("category", "ALTER TABLE businesses ADD COLUMN category TEXT"),
        ("opening_hours", "ALTER TABLE businesses ADD COLUMN opening_hours TEXT"),
    ):
        if name not in cols:
            await conn.exec_driver_sql(ddl)


async def _ensure_query_indexes(conn: AsyncConnection) -> None:
    """Create the hot-path indexes on a database that already has its tables.

    ``create_all`` skips existing tables *and their indexes*, so a database created before these
    were declared would keep doing full scans forever without this pass. Idempotent, and the
    names match the ones on the models so both paths converge on the same index.
    """
    for ddl in _QUERY_INDEX_DDL:
        await conn.exec_driver_sql(ddl)


async def init_db() -> None:
    """Create tables (no-op if present), migrate, and add the hot-path indexes."""
    import os

    from . import models  # noqa: F401  (register all models)

    if _SQLITE:
        path = _settings.database_url.split("///", 1)[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if _SQLITE:
            await _migrate_performance_table(conn)
            await _migrate_business_detail_columns(conn)
            await _ensure_query_indexes(conn)


async def checkpoint_and_optimize() -> tuple[int, int, int] | None:
    """Fold the WAL back into the main file and refresh the planner's statistics.

    SQLite auto-checkpoints but never shrinks the WAL, so a long-lived server leaves it at its
    high-water mark (this project's measured 4.1MB against a 196KB database) and every reader
    pays to walk it. TRUNCATE is best-effort: if another connection is mid-read SQLite declines
    to shrink and just reports how far it got, and the next pass catches up.

    Returns ``(busy, wal_frames, frames_written)``, or None on a non-SQLite backend.
    """
    if not _SQLITE:
        return None
    async with engine.connect() as conn:
        busy, frames, written = (await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")).one()
        await conn.exec_driver_sql("PRAGMA optimize")
        await conn.commit()
    if busy:
        log.debug("WAL checkpoint deferred: %d of %d frames written", written, frames)
    else:
        log.debug("WAL truncated after checkpoint (%d frames)", frames)
    return int(busy), int(frames), int(written)


async def dispose_engine() -> None:
    if _SQLITE:
        try:
            await checkpoint_and_optimize()
        except Exception:  # pragma: no cover - shutdown must not fail on a busy file
            log.debug("WAL checkpoint on shutdown skipped", exc_info=True)
    await engine.dispose()
