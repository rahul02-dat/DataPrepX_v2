"""Thin synchronous Postgres access for lineage writes (Phase 2 scope).

Deliberately synchronous / psycopg2-based, not SQLAlchemy or asyncpg. Phase 2's gate-check and
replay flows are one-shot CLI invocations, not FastAPI request-path code. Async, Celery-driven
writes are Phase 8 work — don't pull that forward here.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


@contextmanager
def get_connection() -> Iterator["psycopg2.extensions.connection"]:
    conn = psycopg2.connect(_database_url())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()