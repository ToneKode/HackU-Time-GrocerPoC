"""Apply schema.sql to DATABASE_URL. Safe to run repeatedly."""
from __future__ import annotations

import sys

from config import settings
from db import apply_schema, ping


def main() -> int:
    s = settings()
    print(f"Migrating {s['database_url'].split('@')[-1]} ...")
    apply_schema(s["database_url"], s["schema_path"])
    ok = ping(s["database_url"])
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
