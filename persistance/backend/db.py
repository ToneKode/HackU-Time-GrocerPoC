"""Postgres connection helpers (psycopg3)."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def connect(database_url: str):
    return psycopg.connect(database_url, row_factory=dict_row)


@contextmanager
def cursor(database_url: str):
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            yield conn, cur
        conn.commit()


def apply_schema(database_url: str, schema_path: str | Path) -> None:
    sql = Path(schema_path).read_text(encoding="utf-8")
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def ping(database_url: str) -> bool:
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() is not None
