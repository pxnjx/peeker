"""Declarative base for all ORM models."""
import datetime as dt

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    """Aware UTC now — one definition, shared by models, alerts, worker, scheduler and API."""
    return dt.datetime.now(dt.UTC)
