"""Turn a model decision into one catalog product.

The model may name a query, a quantity, and a sell point. The shelf is
the source of truth: a sell point the shopper asked for wins over a sku
the model invented.
"""

from __future__ import annotations

import re

SELL_POINTS = ("cheap", "highest_usage", "best_rating")
_STOP = {
    "buy",
    "please",
    "a",
    "an",
    "the",
    "some",
    "me",
    "for",
    "of",
    "my",
    "i",
    "want",
    "get",
    "need",
}


def normalize_sell_point(value: str) -> str:
    text = value.casefold().replace("-", " ").replace("_", " ").strip()
    if text in {"cheap", "cheapest", "budget", "lowest", "lowest price", "value"}:
        return "cheap"
    if "usage" in text or "popular" in text or "everyday" in text or "most used" in text:
        return "highest_usage"
    if "rating" in text or text in {"best", "best rated", "top", "top rated"}:
        return "best_rating"
    return ""


def resolve_pick(catalog: list[dict], decision: dict) -> dict | None:
    query = str(decision.get("query") or "").strip()
    sell = normalize_sell_point(str(decision.get("sell_point") or ""))
    sku = str(decision.get("sku") or "").strip()
    hits = _match_query(catalog, query) if query else list(catalog)
    if sell:
        pointed = [item for item in hits if item.get("sell_point") == sell]
        if pointed:
            hits = pointed
    if sku:
        named = next((item for item in hits if item["id"] == sku), None)
        if named:
            return named
    if hits:
        return hits[0]
    if sku and sell:
        named = next((item for item in catalog if item["id"] == sku), None)
        if named and named.get("sell_point") == sell:
            return named
    return None


def goal_from(intent: str, decision: dict, product: dict | None = None) -> dict:
    try:
        qty = max(1, int(decision.get("qty") or 1))
    except (TypeError, ValueError):
        qty = 1
    sell = normalize_sell_point(str(decision.get("sell_point") or ""))
    if product and not sell:
        sell = str(product.get("sell_point") or "")
    thought = str(decision.get("thought") or "").strip() or "Read the sentence and pick a shelf."
    return {
        "intent": intent,
        "query": str(decision.get("query") or "").strip(),
        "qty": qty,
        "sell_point": sell,
        "sku": product["id"] if product else str(decision.get("sku") or ""),
        "thought": thought,
        "model": str(decision.get("model") or ""),
    }


def _match_query(catalog: list[dict], query: str) -> list[dict]:
    needle = query.casefold()
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", needle) if tok and tok not in _STOP]
    found = []
    for item in catalog:
        hay = " ".join(
            [
                str(item.get("name", "")),
                str(item.get("category", "")),
                str(item.get("merchant", "")),
                str(item.get("sell_point", "")),
            ]
        ).casefold()
        if needle and needle in hay:
            found.append(item)
            continue
        if tokens and all(tok in hay for tok in tokens):
            found.append(item)
    return found
