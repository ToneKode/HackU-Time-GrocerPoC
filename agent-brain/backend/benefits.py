"""Merchant offers and connected-card benefits.

The shopper model is qwen/qwen3.6-flash: about 1,000,000 input tokens and
65,536 output tokens. Comparing one basket does not need a second call.
The planner still sees at most 40 catalogue rows and max_tokens stays 1600.
This module scores the shelf the agent already loaded, one item at a time.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import math

_RULES = ContextVar("merchant_rules", default=None)


def validate_rules(rules: dict) -> dict:
    """Validate a live snapshot; an empty promotions list disables demo offers."""
    if not isinstance(rules, dict) or type(rules.get("version")) is not int or rules["version"] < 0:
        raise ValueError("Rules need a nonnegative integer version")
    if not isinstance(rules.get("promotions"), list):
        raise ValueError("Rules need a promotions array")
    checked = deepcopy(rules)
    seen = set()
    for row in checked["promotions"]:
        if not isinstance(row, dict):
            raise ValueError("Promotion must be an object")
        for key in ("id", "merchant"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Promotion needs {key}")
        if row["id"] in seen:
            raise ValueError("Duplicate promotion id")
        seen.add(row["id"])
        if row.get("kind") not in {"percent", "bogo"} or type(row.get("enabled", True)) is not bool:
            raise ValueError("Invalid promotion kind or enabled flag")
        row.setdefault("enabled", True)
        row.setdefault("threshold", 0)
        if isinstance(row["threshold"], bool) or not isinstance(row["threshold"], (int, float)) or not math.isfinite(row["threshold"]) or row["threshold"] < 0:
            raise ValueError("Promotion threshold must be finite and nonnegative")
        if row["kind"] == "percent":
            rate = row.get("rate")
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 0 <= rate <= 1:
                raise ValueError("Percent rate must be a fraction between zero and one")
            if row.get("sku"):
                raise ValueError("Percent promotions apply to merchant subtotals")
        else:
            if not isinstance(row.get("sku"), str) or not row["sku"].strip():
                raise ValueError("BOGO needs a SKU")
            for key in ("buy_qty", "gift_qty"):
                row.setdefault(key, 1)
                if type(row[key]) is not int or row[key] < 1:
                    raise ValueError(f"{key} must be a positive integer")
    if "payment_promotions" in checked:
        if not isinstance(checked["payment_promotions"], list):
            raise ValueError("Rules need a payment_promotions array")
        payment_keys = set()
        for row in checked["payment_promotions"]:
            if not isinstance(row, dict):
                raise ValueError("Payment promotion must be an object")
            route = row.get("route")
            if not isinstance(route, str) or not route.strip():
                raise ValueError("Payment promotion needs a route")
            row["route"] = route.strip().casefold()
            kind = row.get("kind")
            if not isinstance(kind, str):
                raise ValueError("Invalid payment promotion kind")
            spelling = kind.strip().casefold().replace(" ", "").replace("_", "").replace("-", "")
            kinds = {value.replace("_", ""): value for value in BENEFIT_KINDS}
            if spelling not in kinds:
                raise ValueError("Invalid payment promotion kind")
            row["kind"] = kinds[spelling]
            row.setdefault("merchant", "")
            if not isinstance(row["merchant"], str):
                raise ValueError("Payment promotion merchant must be a string")
            row["merchant"] = row["merchant"].strip()
            row.setdefault("enabled", True)
            if type(row["enabled"]) is not bool:
                raise ValueError("Invalid payment promotion enabled flag")
            rate = row.get("rate")
            limit = 1 if row["kind"] == "cash" else 1_000_000
            if (isinstance(rate, bool) or not isinstance(rate, (int, float))
                    or not 0 <= rate <= limit or not math.isfinite(rate)):
                raise ValueError(f"Payment {row['kind']} rate must be finite and between zero and {limit}")
            key = (row["route"], row["kind"], row["merchant"])
            if key in payment_keys:
                raise ValueError("Duplicate payment promotion route, kind and merchant")
            payment_keys.add(key)
    return checked


def current_rules(rules: dict | None = None) -> dict | None:
    return validate_rules(rules) if rules is not None else _RULES.get()


@contextmanager
def rules_context(rules: dict):
    """Bind one validated snapshot for this request, restoring it on exit."""
    token = _RULES.set(validate_rules(rules))
    try:
        yield _RULES.get()
    finally:
        _RULES.reset(token)


def gift_lines(lines: list[dict], rules: dict | None = None) -> list[dict]:
    """Derive same-SKU gifts exclusively from purchased quantities."""
    snapshot = current_rules(rules)
    if snapshot is None:
        return []
    paid = [line for line in lines if not line.get("is_gift")]
    totals = {}
    grouped = {}
    for line in paid:
        merchant = str(line.get("merchant") or "Shop")
        totals[merchant] = totals.get(merchant, 0) + float(line.get("line_total") or 0)
        key = (merchant, str(line.get("sku") or line.get("id") or ""))
        grouped.setdefault(key, []).append(line)
    gifts = []
    # Multiple offers for one SKU do not stack; the largest gift wins.
    for (merchant, sku), group in grouped.items():
        qty = sum(int(line["qty"]) for line in group)
        eligible = [row for row in snapshot["promotions"] if row["enabled"] and row["kind"] == "bogo"
                    and row["merchant"] == merchant and row["sku"] == sku
                    and _money(totals[merchant]) >= row["threshold"]]
        if not eligible:
            continue
        promo = max(eligible, key=lambda row: (qty // row["buy_qty"] * row["gift_qty"], row["id"]))
        count = qty // promo["buy_qty"] * promo["gift_qty"]
        if count:
            base = group[0]
            gifts.append({**base, "sku": sku, "qty": count, "unit_price": 0.0, "price": 0.0,
                          "line_total": 0.0, "is_gift": True, "gift_for_sku": sku,
                          "purchased_qty": qty, "promotion_id": promo["id"], "rules_version": snapshot["version"],
                          "product_reason": f"Free gift from promotion {promo["id"]}",
                          "merchant_reason": "Included at no charge with the purchased product."})
    return gifts

BENEFIT_KINDS = ("cash", "asiamiles", "membership_points", "loyalty_points")
DEFAULT_RANK = list(BENEFIT_KINDS)

INSTRUMENTS = (
    {
        "route": "mastercard",
        "label": "Mox Mastercard",
        "bank": "Mox",
        "keys": ("mox", "mastercard"),
        "cashback": 0.024,
        "membership_points_per_hkd": 1.0,
    },
    {
        "route": "alipay",
        "label": "Alipay",
        "bank": "Alipay",
        "keys": ("alipay",),
        "loyalty_points_per_hkd": 0.25,
    },
    {
        "route": "visa",
        "label": "ICBC Visa",
        "bank": "ICBC",
        "keys": ("icbc", "visa"),
        "asiamiles_per_hkd": 0.125,
    },
)


def default_methods() -> list[dict]:
    """Used when the shopper has no saved cards. Mastercard is the demo default."""
    return [
        {
            "route": "mastercard",
            "label": "Mox Mastercard",
            "last4": "4242",
            "connected": True,
        }
    ]


def connected_methods(methods: list[dict] | None) -> list[dict]:
    """None means the demo card. A saved list uses only the connected rows."""
    if methods is None:
        return default_methods()
    return [row for row in methods if row.get("connected", True)]


def _instrument_for(method: dict) -> dict:
    text = f"{method.get('label') or ''} {method.get('route') or ''}".casefold()
    route = str(method.get("route") or "").casefold()
    if route and route not in {instrument["route"] for instrument in INSTRUMENTS}:
        return {"route": route, "label": method.get("label") or "Card",
                "bank": method.get("bank") or method.get("label") or "Card", "keys": ()}
    for instrument in INSTRUMENTS:
        if method.get("route") == instrument["route"] or any(key in text for key in instrument["keys"]):
            return instrument
    return {
        "route": method.get("route") or "mastercard",
        "label": method.get("label") or "Card",
        "bank": method.get("label") or "Card",
        "keys": (),
    }


def _money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def quote_tender(merchant: str, subtotal: float, method: dict, *, rules: dict | None = None) -> dict:
    """One merchant, one connected tender. Discount stays off the policy amount."""
    instrument = _instrument_for(method)
    subtotal = _money(subtotal)
    if not method.get("connected", True) or (method.get("merchants") and merchant not in method["merchants"]):
        return {"route": "", "label": "No connected card", "bank": "", "last4": "",
                "discount": 0.0, "payable": subtotal, "benefits": [],
                "because": "This payment method is unavailable for this merchant.",
                "rates": {kind: 0.0 for kind in BENEFIT_KINDS}}
    discount = 0.0
    notes: list[str] = []
    snapshot = current_rules(rules)
    if snapshot is not None:
        offers = [row for row in snapshot["promotions"] if row["enabled"] and row["kind"] == "percent"
                  and row["merchant"] == merchant and subtotal >= row["threshold"]]
        if offers:
            offer = max(offers, key=lambda row: (row["rate"], row["id"]))
            discount = _money(subtotal * offer["rate"])
            notes.append(f"Promotion {offer["id"]}: {offer["rate"] * 100:g}% off at HK${offer["threshold"]:g}")
    elif merchant == "Watsons" and subtotal >= 300:
        discount = _money(subtotal * 0.15)
        notes.append("Demo Watsons offer: goods of at least HK$300 get 15% off")
    elif merchant == "PARKnSHOP" and subtotal >= 300:
        discount = _money(subtotal * 0.10)
        notes.append("Demo PARKnSHOP offer: goods of at least HK$300 get 10% off")
    payable = _money(subtotal - discount)
    benefits: list[dict] = []
    route = instrument["route"]
    configured_rates = None
    if snapshot is not None and "payment_promotions" in snapshot:
        selected = {}
        for row in snapshot["payment_promotions"]:
            if row["route"] != route or row["merchant"] not in ("", merchant):
                continue
            previous = selected.get(row["kind"])
            if previous is None or row["merchant"]:
                selected[row["kind"]] = row
        configured_rates = {kind: 0.0 for kind in BENEFIT_KINDS}
        labels = {"cash": "cashback", "asiamiles": "Asia Miles",
                  "membership_points": "membership points", "loyalty_points": "loyalty points"}
        for kind in BENEFIT_KINDS:
            row = selected.get(kind)
            if row is None or not row["enabled"]:
                continue
            rate = float(row["rate"])
            configured_rates[kind] = rate
            amount = _money(payable * rate)
            rate_text = f"{rate * 100:g}% cashback" if kind == "cash" else f"{rate:g} {labels[kind]} per HK$1"
            detail = f"{rate_text} on {instrument['label']}: {amount:.2f} earned on HK${payable:.2f} discounted goods"
            if amount:
                benefits.append({"kind": kind, "amount": amount, "detail": detail})
            notes.append(detail)
    elif route == "mastercard":
        multiplier = 2 if merchant == "Watsons" else 1
        points = _money(payable * float(instrument.get("membership_points_per_hkd") or 1) * multiplier)
        benefits.append(
            {
                "kind": "membership_points",
                "amount": points,
                "detail": f"{multiplier}x membership points on {instrument['label']}",
            }
        )
        cash = _money(payable * float(instrument.get("cashback") or 0))
        if cash:
            benefits.append(
                {
                    "kind": "cash",
                    "amount": cash,
                    "detail": f"2.4% cashback on {instrument['label']}",
                }
            )
        if multiplier == 2:
            notes.append("Paying by Mastercard earns 2x membership points at Watsons")
    elif route == "alipay":
        points = _money(payable * float(instrument.get("loyalty_points_per_hkd") or 0.25))
        benefits.append(
            {
                "kind": "loyalty_points",
                "amount": points,
                "detail": f"Loyalty points on {instrument['label']}",
            }
        )
        notes.append(f"Alipay earns loyalty points at {merchant}")
    elif route == "visa":
        miles = _money(payable * float(instrument.get("asiamiles_per_hkd") or 0.125))
        if miles:
            benefits.append(
                {
                    "kind": "asiamiles",
                    "amount": miles,
                    "detail": f"Asia Miles on {instrument['label']}",
                }
            )
        notes.append(f"ICBC Visa earns Asia Miles at {merchant}")
    because = " ".join(notes) if notes else f"{instrument['label']} is a connected way to pay {merchant}."
    rates = {kind: 0.0 for kind in BENEFIT_KINDS}
    if configured_rates is not None:
        rates.update({kind: rate * payable / subtotal if subtotal else 0.0
                      for kind, rate in configured_rates.items()})
    elif route == "mastercard":
        rates["cash"] = float(instrument.get("cashback") or 0)
        rates["membership_points"] = float(instrument.get("membership_points_per_hkd") or 1) * (
            2 if merchant == "Watsons" else 1
        )
    elif route == "alipay":
        rates["loyalty_points"] = float(instrument.get("loyalty_points_per_hkd") or 0.25)
    elif route == "visa":
        rates["asiamiles"] = float(instrument.get("asiamiles_per_hkd") or 0.125)
    if discount and subtotal:
        rates["cash"] += discount / subtotal
    return {
        "route": route,
        "label": instrument["label"],
        "bank": instrument["bank"],
        "last4": method.get("last4") or "",
        "discount": discount,
        "payable": payable,
        "benefits": benefits,
        "because": because,
        "rates": rates,
    }


def benefit_rates(tender: dict) -> dict[str, float]:
    """Benefit per HK$1 of shelf price, so a ranking can change the card."""
    stored = tender.get("rates")
    if isinstance(stored, dict):
        return {kind: float(stored.get(kind) or 0) for kind in BENEFIT_KINDS}
    return {kind: 0.0 for kind in BENEFIT_KINDS}


def _rank_order(rank: list[str] | None) -> list[str]:
    order = [kind for kind in (rank or DEFAULT_RANK) if kind in BENEFIT_KINDS]
    for kind in DEFAULT_RANK:
        if kind not in order:
            order.append(kind)
    return order


def _tender_sort_key(tender: dict, rank: list[str] | None) -> tuple:
    rates = benefit_rates(tender)
    return tuple(-rates[kind] for kind in _rank_order(rank)) + (float(tender.get("payable") or 0),)


def choose_tender(merchant: str, subtotal: float, methods: list[dict] | None, rank: list[str] | None, *, rules: dict | None = None) -> dict:
    """The shopper's first-ranked benefit picks the card. Later ranks break ties."""
    order = _rank_order(rank)
    pool = [
        method for method in connected_methods(methods)
        if not method.get("merchants") or merchant in method["merchants"]
    ]
    if not pool:
        return {
            "route": "",
            "label": "No connected card",
            "bank": "",
            "last4": "",
            "discount": 0.0,
            "payable": _money(subtotal),
            "benefits": [],
            "because": "No connected payment method is available for this merchant.",
            "score": 0.0,
        }
    best = None
    best_key = None
    for method in pool:
        quote = quote_tender(merchant, subtotal, method, rules=rules)
        key = _tender_sort_key(quote, order)
        if best is None or key < best_key:
            best = quote
            best_key = key
    assert best is not None
    best["score"] = round(benefit_rates(best).get(order[0], 0.0), 4)
    return best


def merchant_benefit_score(
    merchant: str,
    subtotal: float,
    methods: list[dict] | None,
    rank: list[str] | None,
) -> float:
    return float(choose_tender(merchant, subtotal, methods, rank)["score"])


def _item_sell_rank(item: dict, sell: str) -> int:
    if sell:
        return 0 if item.get("sell_point") == sell else 1
    order = {"best_rating": 0, "highest_usage": 1, "cheap": 2}
    return order.get(str(item.get("sell_point") or ""), 3)


def _unit_price(item: dict) -> float:
    return float(item.get("price") or 0)


def rank_candidates(
    options: list[dict],
    need: dict,
    methods: list[dict] | None,
    rank: list[str] | None,
) -> list[dict]:
    """Sell point first, then the close-price band, then the ranked card benefit.

    A much cheaper row wins. A payment promotion wins only inside HK$3 or 8%
    of that price, so a large cashback on an expensive row cannot jump the queue.
    """
    if not options:
        return []
    sell = str(need.get("sell_point") or "")
    qty = max(1, int(need.get("qty") or 1))
    best_rank = min(_item_sell_rank(item, sell) for item in options)
    pool = [item for item in options if _item_sell_rank(item, sell) == best_rank]
    pool_ids = {id(item) for item in pool}
    rest = [item for item in options if id(item) not in pool_ids]
    floor = min(_unit_price(item) for item in pool)
    band = max(floor * 0.08, 3.0)
    close = [item for item in pool if _unit_price(item) <= floor + band + 0.001]
    close_ids = {id(item) for item in close}
    far = [item for item in pool if id(item) not in close_ids]

    def pref_key(item: dict) -> tuple:
        tender = choose_tender(str(item.get("merchant") or ""), _unit_price(item) * qty, methods, rank)
        return _tender_sort_key(tender, rank) + (_unit_price(item), str(item.get("id") or ""))

    close.sort(key=pref_key)
    far.sort(key=lambda item: (_unit_price(item), str(item.get("id") or "")))
    rest.sort(key=lambda item: (_item_sell_rank(item, sell), _unit_price(item), str(item.get("id") or "")))
    return close + far + rest


def explain_pick(
    need: dict,
    product: dict,
    options: list[dict],
    methods: list[dict] | None = None,
    rank: list[str] | None = None,
) -> str:
    """One block per item. Newlines are the line-by-line observation."""
    qty = max(1, int(need.get("qty") or 1))
    price = float(product.get("price") or 0)
    asked = need.get("sell_point") or "no sell point"
    marked = product.get("sell_point") or "unranked"
    sell = str(need.get("sell_point") or "")
    group = [item for item in options if _item_sell_rank(item, sell) == _item_sell_rank(product, sell)] or [product]
    cheapest_same = min(group, key=lambda item: (_unit_price(item), str(item.get("id") or "")))
    floor = _unit_price(cheapest_same)
    band = max(floor * 0.08, 3.0)
    rows = [
        (
            f"{product.get('name')} from {product.get('merchant')} "
            f"at HK${price:.2f}, qty {qty}."
        ),
        f"The request asked for {asked}. This catalogue row is marked {marked}.",
    ]
    if cheapest_same.get("id") == product.get("id"):
        rows.append(
            f"Among {len(group)} similar rows at this sell point, "
            "this is the best quantity per dollar "
            f"at HK${price:.2f}."
        )
    else:
        rows.append(
            f"The lowest similar price is {cheapest_same.get('name')} from {cheapest_same.get('merchant')} "
            f"at HK${floor:.2f}. This row is HK${price - floor:.2f} more, inside HK${band:.2f}, "
            "so the quantity per dollar stays close and the payment promotion wins."
        )
    others = [item for item in group if item.get("id") != product.get("id")]
    if others:
        nxt = min(others, key=lambda item: (_unit_price(item), str(item.get("id") or "")))
        rows.append(
            f"The next similar row is {nxt.get('name')} from {nxt.get('merchant')} "
            f"at HK${_unit_price(nxt):.2f}."
        )
    rated = [item for item in options if item.get("sell_point") == "best_rating"]
    if marked == "best_rating":
        rows.append("Among this set, this is the best-rated row.")
    elif rated:
        top = min(rated, key=lambda item: (_unit_price(item), str(item.get("id") or "")))
        rows.append(
            f"The best-rated row in this set is {top.get('name')} from {top.get('merchant')} "
            f"at HK${_unit_price(top):.2f}."
        )
    if options:
        cheapest = min(options, key=lambda item: (_unit_price(item), str(item.get("id") or "")))
        if cheapest.get("id") != product.get("id"):
            rows.append(
                f"The lowest price in the whole set is {cheapest.get('name')} from {cheapest.get('merchant')} "
                f"at HK${_unit_price(cheapest):.2f}, marked {cheapest.get('sell_point') or 'unranked'}."
            )
    if need.get("merchant") and asked not in {"", "no sell point"} and marked != asked:
        rows.append(
            f"{need['merchant']} has no {asked} match, so this is the one that shop stocks."
        )
    tender = choose_tender(str(product.get("merchant") or ""), price * qty, methods, rank)
    labels = {
        "cash": "cashback",
        "asiamiles": "Asia Miles",
        "membership_points": "membership points",
        "loyalty_points": "loyalty points",
    }
    order = ", ".join(labels.get(kind, kind) for kind in _rank_order(rank))
    rows.append(
        f"For {product.get('merchant')}, the connected tender is {tender['label']}. {tender['because']}"
    )
    rows.append(f"Benefit ranking checked in this order: {order}.")
    return "\n".join(rows)


def settlement_for(
    lines: list[dict],
    quote: dict,
    methods: list[dict] | None = None,
    rank: list[str] | None = None,
    *, rules: dict | None = None,
) -> dict:
    """Overall total, with one tender per merchant. Shipping is added to the largest tender."""
    snapshot = current_rules(rules)
    lines = [line for line in lines if not line.get("is_gift")]
    lines = lines + gift_lines(lines, snapshot)
    groups: dict[str, list[dict]] = {}
    for line in lines:
        groups.setdefault(line.get("merchant") or "Shop", []).append(line)
    merchants = []
    discount = 0.0
    goods = 0.0
    combined_benefits: dict[str, dict] = {}
    for merchant, group in groups.items():
        subtotal = _money(sum(float(line.get("line_total") or 0) for line in group))
        tender = choose_tender(merchant, subtotal, methods, rank, rules=snapshot)
        discount = _money(discount + tender["discount"])
        goods = _money(goods + tender["payable"])
        for benefit in tender["benefits"]:
            slot = combined_benefits.setdefault(
                benefit["kind"],
                {"kind": benefit["kind"], "amount": 0.0, "detail": benefit["detail"]},
            )
            slot["amount"] = _money(slot["amount"] + float(benefit["amount"]))
        merchants.append(
            {
                "merchant": merchant,
                "subtotal": subtotal,
                "discount": tender["discount"],
                "payable": tender["payable"],
                "payment": {
                    "route": tender["route"],
                    "label": tender["label"],
                    "bank": tender["bank"],
                    "last4": tender["last4"],
                    "amount": tender["payable"],
                },
                "benefits": tender["benefits"],
                "because": tender["because"],
                "lines": [
                    {
                        **{key: line[key] for key in ("is_gift", "gift_for_sku", "purchased_qty", "promotion_id", "rules_version") if key in line},
                        "sku": line.get("sku"),
                        "name": line.get("name"),
                        "qty": int(line.get("qty") or 1),
                        "unit_price": _money(line.get("unit_price") or 0),
                        "line_total": _money(line.get("line_total") or 0),
                        "image_url": line.get("image_url") or "",
                        "merchant": merchant,
                    }
                    for line in group
                ],
            }
        )
    shipping = _money((quote or {}).get("shipping_fee") or 0)
    tax = _money((quote or {}).get("tax") or 0)
    if merchants and (shipping or tax):
        host = max(merchants, key=lambda row: row["payable"])
        host["payment"]["amount"] = _money(host["payment"]["amount"] + shipping + tax)
    total = _money(goods + shipping + tax)
    subtotal = _money(sum(float(line.get("line_total") or 0) for line in lines))
    return {
        "rules_version": snapshot["version"] if snapshot is not None else None,
        "currency": (quote or {}).get("currency") or "HKD",
        "subtotal": subtotal,
        "discount": discount,
        "shipping_fee": shipping,
        "tax": tax,
        "total": total,
        "shelf_total": _money((quote or {}).get("total_landed_cost") or total),
        "merchants": merchants,
        "benefits": list(combined_benefits.values()),
    }
