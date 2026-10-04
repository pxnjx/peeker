"""FastAPI application entrypoint: wires DB, scheduler, worker pool, and routes."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Security
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .auth import require_session
from .config import get_settings
from .crawler import close_crawler, get_crawler
from .db import dispose_engine, init_db
from .scheduler import build_scheduler
from .worker import WorkerPool

settings = get_settings()
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler = build_scheduler()
    pool = WorkerPool(get_crawler())
    scheduler.start()
    await pool.start()
    app.state.scheduler = scheduler
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.stop()
        scheduler.shutdown(wait=False)
        await close_crawler()
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Every data route behind one dependency: no dashboard session cookie, no data.
    # /health and / below stay open on purpose - they expose nothing but the app name and
    # are what uptime probes and container checks hit before anything is signed in.
    app.include_router(router, dependencies=[Security(require_session)])

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    @app.get("/")
    async def root() -> dict:
        return {"app": settings.app_name, "docs": "/docs", "health": "/health", "stats": "/api/stats"}

    return app


app = create_app()


def main() -> None:  # pragma: no cover - manual entrypoint
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
