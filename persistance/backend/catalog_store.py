"""Product shelf stored in MySQL.

Rows match agent-brain/hk_products_full.json. Search is bounded so a caller
can ask for a page instead of all 5,000 products.
"""
from __future__ import annotations

from db import connect


def normalize_product(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    sku = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    merchant = str(item.get("merchant") or "").strip()
    category = str(item.get("category") or "").strip()
    if not sku or not name or not merchant or not category:
        return None
    try:
        price = round(float(item["price"]), 2)
    except (KeyError, TypeError, ValueError):
        return None
    if price < 0:
        return None
    currency = str(item.get("currency") or "HKD").strip().upper() or "HKD"
    raw_stock = item.get("stock")
    stock = None
    if raw_stock is not None and raw_stock != "":
        try:
            stock = int(raw_stock)
        except (TypeError, ValueError):
            stock = None
    image = str(item.get("image_url") or "").strip() or None
    url = str(item.get("product_url") or "").strip() or None
    return {
        "id": sku,
        "name": name,
        "price": price,
        "currency": currency[:3],
        "merchant": merchant,
        "category": category,
        "stock": stock,
        "in_stock": bool(item.get("in_stock", True)),
        "image_url": image,
        "sell_point": str(item.get("sell_point") or ""),
        "product_url": url,
    }


def _public(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "price": float(row["price"]),
        "currency": str(row["currency"]).strip(),
        "merchant": row["merchant"],
        "category": row["category"],
        "stock": row["stock"],
        "in_stock": bool(row["in_stock"]),
        "image_url": row["image_url"],
        "sell_point": row["sell_point"] or "",
        "product_url": row["product_url"],
    }


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_UPSERT = """
INSERT INTO catalog_products (
    id, name, price, currency, merchant, category,
    stock, in_stock, image_url, sell_point, product_url
) VALUES (
    %(id)s, %(name)s, %(price)s, %(currency)s, %(merchant)s, %(category)s,
    %(stock)s, %(in_stock)s, %(image_url)s, %(sell_point)s, %(product_url)s
)
AS new_row
ON DUPLICATE KEY UPDATE
    name = new_row.name,
    price = new_row.price,
    currency = new_row.currency,
    merchant = new_row.merchant,
    category = new_row.category,
    stock = new_row.stock,
    in_stock = new_row.in_stock,
    image_url = new_row.image_url,
    sell_point = new_row.sell_point,
    product_url = new_row.product_url,
    updated_at = CURRENT_TIMESTAMP(6)
"""

_SELECT = """
SELECT id, name, price, currency, merchant, category,
       stock, in_stock, image_url, sell_point, product_url
FROM catalog_products
"""


class CatalogStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def upsert_many(self, items: list[dict]) -> dict:
        by_id: dict[str, dict] = {}
        skipped = 0
        for item in items:
            row = normalize_product(item)
            if row is None:
                skipped += 1
                continue
            by_id[row["id"]] = row
        rows = list(by_id.values())
        if rows:
            with connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.executemany(_UPSERT, rows)
                conn.commit()
        return {"upserted": len(rows), "skipped": skipped}

    def count(self) -> int:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM catalog_products")
                return int(cur.fetchone()["n"])

    def get(self, sku: str) -> dict | None:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT + " WHERE id = %s", (sku,))
                row = cur.fetchone()
        return _public(row) if row else None

    def search(
        self,
        q: str = "",
        merchant: str = "",
        category: str = "",
        limit: int = 48,
        offset: int = 0,
    ) -> list[dict]:
        q = (q or "").strip()
        merchant = (merchant or "").strip()
        category = (category or "").strip()
        limit = max(1, min(int(limit), 6000))
        offset = max(0, int(offset))
        sql = _SELECT + """
        WHERE (%(q)s = '' OR name LIKE %(like)s ESCAPE '\\\\'
               OR merchant LIKE %(like)s ESCAPE '\\\\'
               OR category LIKE %(like)s ESCAPE '\\\\'
               OR id LIKE %(like)s ESCAPE '\\\\'
               OR sell_point LIKE %(like)s ESCAPE '\\\\')
          AND (%(merchant)s = '' OR merchant = %(merchant)s)
          AND (%(category)s = '' OR category = %(category)s)
        ORDER BY name, id
        LIMIT %(limit)s OFFSET %(offset)s
        """
        params = {
            "q": q,
            "like": _like(q) if q else "",
            "merchant": merchant,
            "category": category,
            "limit": limit,
            "offset": offset,
        }
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_public(row) for row in rows]

    def categories(self) -> list[dict]:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT category, COUNT(*) AS n
                    FROM catalog_products
                    GROUP BY category
                    ORDER BY category
                    """
                )
                rows = cur.fetchall()
        return [{"category": row["category"], "count": int(row["n"])} for row in rows]
