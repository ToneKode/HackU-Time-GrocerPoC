"""MySQL connection helpers (PyMySQL)."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import pymysql
from pymysql.err import OperationalError, ProgrammingError

_IDENT = re.compile(r"^[A-Za-z0-9_]+$")
# Index already exists. Re-applying schema.sql is expected.
_IGNORE = {1061}


def parse_mysql_url(database_url: str) -> dict:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError("DATABASE_URL must start with mysql://")
    name = parsed.path.lstrip("/")
    if name and not _IDENT.match(name):
        raise ValueError("Database name must be letters, numbers, and underscores")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": name or None,
    }


class _Session:
    """Commit when the block finishes cleanly. PyMySQL only closes the connection."""

    def __init__(self, raw):
        self._raw = raw

    def __enter__(self):
        return self._raw

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._raw.commit()
            else:
                self._raw.rollback()
        finally:
            self._raw.close()


def connect(database_url: str, *, with_database: bool = True):
    cfg = parse_mysql_url(database_url)
    raw = pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"] if with_database else None,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
    )
    return _Session(raw)


def ensure_database(database_url: str) -> str:
    """Create the database named in the URL. The login needs CREATE privilege."""
    name = parse_mysql_url(database_url)["database"]
    if not name:
        raise ValueError("DATABASE_URL is missing a database name")
    with connect(database_url, with_database=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    return name


def _statements(sql: str) -> list[str]:
    parts = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buf).strip().rstrip(";").strip()
            buf = []
            if statement:
                parts.append(statement)
    tail = "\n".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def apply_schema(database_url: str, schema_path: str | Path) -> None:
    sql = Path(schema_path).read_text(encoding="utf-8")
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            for statement in _statements(sql):
                try:
                    cur.execute(statement)
                except (OperationalError, ProgrammingError) as exc:
                    if exc.args and exc.args[0] in _IGNORE:
                        continue
                    raise
            cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_entries' "
                        "AND COLUMN_NAME IN ('reason', 'thought')")
            for column in cur.fetchall():
                if column["DATA_TYPE"].lower() != "longtext":
                    name = column["COLUMN_NAME"]
                    cur.execute(f"ALTER TABLE audit_entries MODIFY COLUMN `{name}` LONGTEXT NOT NULL")
            cur.execute(
                "SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'payments_status_chk'"
            )
            constraint = cur.fetchone()
            if constraint and "PENDING" not in constraint["CHECK_CLAUSE"]:
                cur.execute("ALTER TABLE payments DROP CHECK payments_status_chk")
                cur.execute(
                    "ALTER TABLE payments ADD CONSTRAINT payments_status_chk CHECK "
                    "(status IN ('DRAFT', 'PENDING', 'AUTHORIZED', 'CAPTURED', 'FAILED', 'REFUNDED'))"
                )
        conn.commit()


def ping(database_url: str) -> bool:
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            return cur.fetchone() is not None
