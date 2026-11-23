"""Explicit database configuration shared by the hosted gateway and its migrator."""

import os

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine, make_url


def hosted_database_url() -> URL | None:
    value = os.environ.get("VOICE_API_DATABASE_URL")
    if not value:
        return None
    url = make_url(value)
    if url.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("VOICE_API_DATABASE_URL requires SQLite or PostgreSQL")
    return url


def hosted_engine(url: URL) -> Engine:
    return create_engine(url, hide_parameters=True, pool_pre_ping=True)
