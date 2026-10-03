"""Load seed JSON into in-memory structures for the mock API."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class Product(BaseModel):
    id: str
    name: str
    price: float
    currency: str
    merchant: str
    category: str
    stock: int
    image_url: str


class MerchantsPayload(BaseModel):
    whitelist: list[str]
    blacklist: list[str]


DATA_DIR = Path(__file__).resolve().parent / "data"


def load_products() -> tuple[list[Product], dict[str, Product]]:
    with (DATA_DIR / "products.json").open(encoding="utf-8") as f:
        products = [Product.model_validate(row) for row in json.load(f)]
    return products, {p.id: p for p in products}


def load_merchants() -> MerchantsPayload:
    with (DATA_DIR / "merchants.json").open(encoding="utf-8") as f:
        return MerchantsPayload.model_validate(json.load(f))
