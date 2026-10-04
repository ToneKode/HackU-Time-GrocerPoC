"""Load agent-brain/hk_products_full.json into catalog_products.

Uses DATABASE_URL from the environment, or MySQL on 127.0.0.1:3306.
Safe to run again: each SKU is updated in place. Prints the host only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from catalog_store import CatalogStore
from config import settings
from db import apply_schema, ensure_database

DEFAULT_JSON = Path(__file__).resolve().parents[2] / "agent-brain" / "hk_products_full.json"


def _safe(exc: BaseException) -> str:
    text = re.sub(r"://[^@\s]+@", "://***@", str(exc))
    return f"{type(exc).__name__}: {text[:300]}"


def main(path: Path | None = None) -> int:
    source = path or DEFAULT_JSON
    items = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        print("Catalog file is not a list")
        return 1
    s = settings()
    host = s["database_url"].split("@")[-1]
    print(f"Loading {len(items)} rows from {source.name} into {host}")
    try:
        ensure_database(s["database_url"])
        apply_schema(s["database_url"], s["schema_path"])
        result = CatalogStore(s["database_url"]).upsert_many(items)
        stored = CatalogStore(s["database_url"]).count()
    except Exception as exc:
        print(_safe(exc))
        return 1
    print(f"Upserted {result['upserted']}, skipped {result['skipped']}, stored {stored}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    sys.exit(main(target))
