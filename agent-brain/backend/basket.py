"""Fit several needs into one cart, then let policy judge each attempt.

The model may name the needs. Prices, the payment route, and every
pass / escalate / halt come from the catalog, the mall quote, and the
policy engine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from benefits import explain_pick, rank_candidates
from meal_plan import plan_meal
from pick import _match_query, normalize_sell_point
from policy_rules import CATEGORY_BLACKLIST, WHITELIST

PROMO_PATH = Path(__file__).resolve().parent / "hk_retail_promos_20261003.json"
LINE_HALT = {"category_blacklisted", "merchant_blacklisted", "merchant_not_whitelisted"}
CAP_HALT = {"monthly_cap", "over_bulk_ceiling"}
POLICY_THOUGHT = "Ask the policy engine. This node does not decide."
MAX_ROUNDS = 8


def money(value: float) -> float:
    return round(float(value), 2)


# Queries are product words. The category name "Food" also matches
# "Food Container", so a category label cannot be the search text.
_CATEGORY_QUERY = {
    "Household": "toilet paper",
    "Food": "rice",
    "Beverages": "water",
    "Snacks": "potato chips",
    "Health": "mask",
    "Personal Care": "shampoo",
    "Baby": "diapers",
    "Pets": "dog food",
    "Electronics": "earbuds",
    "Kitchen": "food container",
}


def needs_for_every_category(intent: str, catalog: list[dict]) -> dict | None:
    """One need per shelf category when the sentence asks for all of them.

    Returns None for an ordinary sentence so the model still plans that one.
    """
    text = intent.casefold()
    if not any(phrase in text for phrase in ("every category", "all categor", "each category", "per category")):
        return None
    if "best" in text or "rated" in text:
        sell = "best_rating"
    elif "everyday" in text or "usage" in text:
        sell = "highest_usage"
    else:
        sell = "cheap"
    categories = []
    for item in catalog:
        category = str(item.get("category") or "").strip()
        if category and category not in categories:
            categories.append(category)
    needs = []
    for index, category in enumerate(categories):
        needs.append(
            {
                "query": _CATEGORY_QUERY.get(category) or _fallback_query(catalog, category),
                "qty": 1,
                "sell_point": sell,
                "priority": index + 1,
            }
        )
    label = sell.replace("_", " ")
    return {
        "needs": needs,
        "query": ", ".join(need["query"] for need in needs),
        "qty": len(needs),
        "sell_point": sell,
        "thought": (
            f"The sentence asks for one {label} item from each category. "
            f"Shelf order is {', '.join(categories)}. "
            "Each line is priced, then the policy engine judges that line on its own."
        ),
        "model": "catalog",
    }


_VAGUE = ("something", "whatever", "anything", "not sure", "you decide", "up to you")
_NAMED_PRODUCT = (
    "toilet",
    "rice",
    "water",
    "chip",
    "shampoo",
    "diaper",
    "earbud",
    "mask",
    "dog",
    "container",
)


def plan_fuzzy(intent: str, catalog: list[dict]) -> dict | None:
    """A meal plan is filled from the edible shelf. A sentence with no product asks back."""
    text = intent.casefold()
    if _is_meal_plan(text):
        return plan_meal(intent, catalog)
    if _is_too_vague(text):
        question = "What should I buy, or how many days and what budget should it cover?"
        return {
            "question": question,
            "thought": "The sentence does not name a product, a number of days, or a budget.",
            "reply": question,
            "model": "catalog",
        }
    return None


def _is_meal_plan(text: str) -> bool:
    food = any(word in text for word in ("food", "meal", "ingredient", "grocer"))
    return food and (_days(text) is not None or _budget(text) is not None or "week" in text)


def _is_too_vague(text: str) -> bool:
    if not any(marker in text for marker in _VAGUE):
        return False
    return not any(name in text for name in _NAMED_PRODUCT)


def _days(text: str) -> int | None:
    match = re.search(r"(\d+)\s*days?", text)
    if match:
        return max(1, int(match.group(1)))
    if "a week" in text or "one week" in text or "per week" in text:
        return 7
    return None


def _budget(text: str) -> float | None:
    patterns = (
        r"(?:budget|under|within|hk\$|\$)\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:hkd|hk\$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def _fallback_query(catalog: list[dict], category: str) -> str:
    for item in catalog:
        if item.get("category") == category:
            return str(item.get("name") or category)
    return category


def needs_from(decision: dict) -> list[dict]:
    raw = decision.get("needs")
    if not isinstance(raw, list):
        return []
    needs = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        sell = normalize_sell_point(str(item.get("sell_point") or ""))
        try:
            qty = max(1, int(item.get("qty") or 1))
        except (TypeError, ValueError):
            qty = 1
        try:
            priority = int(item.get("priority") or (index + 1))
        except (TypeError, ValueError):
            priority = index + 1
        row = {
            "query": query,
            "qty": qty,
            "sell_point": sell,
            "explicit": bool(sell),
            "priority": priority,
        }
        sku = str(item.get("sku") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if sku:
            row["sku"] = sku
        if reason:
            row["reason"] = reason
        needs.append(row)
    return needs


_SAME_MERCHANT = (
    "same merchant",
    "same shop",
    "same store",
    "same retailer",
    "one merchant",
    "one shop",
    "one store",
    "single merchant",
    "single shop",
    "single store",
)
_MERCHANT_ALIASES = (
    ("japan home centre", "Japan Home Centre"),
    ("park n shop", "PARKnSHOP"),
    ("parknshop", "PARKnSHOP"),
    ("hktvmall", "HKTVmall"),
    ("watsons", "Watsons"),
    ("jhc", "Japan Home Centre"),
)


def wants_same_merchant(intent: str) -> bool:
    text = intent.casefold()
    return any(phrase in text for phrase in _SAME_MERCHANT)


def named_merchant(intent: str) -> str | None:
    text = intent.casefold()
    for alias, name in _MERCHANT_ALIASES:
        if " " in alias:
            if alias in text:
                return name
            continue
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return name
    return None


def choose_best_merchant(catalog: list[dict], needs: list[dict], intent: str) -> dict:
    """Pick one whitelisted shop. Coverage wins, then payable lines, then landed cost."""
    scored = [_score_merchant(catalog, needs, merchant) for merchant in WHITELIST]
    scored.sort(key=lambda row: (-row["covered"], -row["payable"], row["landed"], row["merchant"]))
    named = named_merchant(intent)
    chosen = next((row for row in scored if row["merchant"] == named), None) if named else scored[0]
    if chosen is None:
        chosen = scored[0]
    return {"merchant": chosen["merchant"], "rows": scored, "reason": _merchant_choice_reason(chosen, scored, named)}


def assign_same_merchant(intent: str, catalog: list[dict], needs: list[dict]) -> dict:
    choice = choose_best_merchant(catalog, needs, intent)
    merchant = choice["merchant"]
    kept = []
    gaps = []
    for need in needs:
        scoped = {**need, "merchant": merchant}
        if options_for(catalog, scoped):
            kept.append(scoped)
        else:
            gaps.append(need["query"])
    reply = choice["reason"]
    if gaps:
        reply += f" {merchant} does not stock {_join_names(gaps)}, so those items are left out."
    return {"merchant": merchant, "needs": kept, "reply": reply}


def options_for(catalog: list[dict], need: dict) -> list[dict]:
    sku = str(need.get("sku") or "").strip()
    if sku:
        pinned = [item for item in catalog if str(item.get("id") or "") == sku]
        merchant = str(need.get("merchant") or "").strip()
        if merchant:
            pinned = [item for item in pinned if item.get("merchant") == merchant]
        if pinned:
            return pinned
    hits = _match_query(catalog, need["query"])
    merchant = str(need.get("merchant") or "").strip()
    if merchant:
        hits = [item for item in hits if item.get("merchant") == merchant]
    sell = need.get("sell_point") or ""
    ranked = []
    seen = set()
    for item in hits:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        ranked.append(item)
    ranked.sort(key=lambda item: (_sell_rank(item, sell), float(item["price"]), item["id"]))
    return ranked


def fit_basket(catalog, needs, monthly_spent, price, policy_check, methods=None, benefit_rank=None) -> dict:
    picked = []
    option_sets = []
    for need in needs:
        options = options_for(catalog, need)
        if not options:
            raise LookupError(f"No product matched {need['query']}")
        option_sets.append(options)
        picked.append(_prefer(options, need, methods, benefit_rank)[0])

    events = []
    repairs = []
    seen = set()
    question = ""
    reply = ""
    policy = None
    quote = None
    lines = []
    rounds = 0
    for round_no in range(1, MAX_ROUNDS + 1):
        signature = tuple(item["id"] for item in picked)
        if signature in seen:
            break
        seen.add(signature)
        drafts = [
            _draft(need, product, option_sets[index], methods, benefit_rank)
            for index, (need, product) in enumerate(zip(needs, picked))
        ]
        quote = price([{"sku": draft["sku"], "qty": draft["qty"]} for draft in drafts])
        lines = _merge(drafts, quote["line_items"])
        events.append(_picked(round_no, lines))
        policy, round_events = policy_check(lines, quote["total_landed_cost"], monthly_spent)
        rounds = round_no
        for event in round_events:
            event["reason"] = f"round {round_no} {event['reason']}"
            events.append(event)
        rule = policy.get("rule") or ""
        if policy["status"] == "PASS":
            break
        if rule in LINE_HALT:
            swapped = _swap_illegal(needs, picked, option_sets, policy)
            if swapped is not None:
                repairs.append(swapped)
                events.append(_revised(swapped))
                continue
            dropped = _blocked_lines(lines, round_events)
            if not dropped:
                break
            kept = len(dropped) < len(lines)
            reply = _blacklist_reply(dropped, kept)
            events.append(_left_out(reply))
            if not kept:
                break
            drop_skus = {line["sku"] for line in dropped}
            kept_indexes = [index for index, line in enumerate(lines) if line["sku"] not in drop_skus]
            needs = [needs[index] for index in kept_indexes]
            picked = [picked[index] for index in kept_indexes]
            option_sets = [option_sets[index] for index in kept_indexes]
            continue
        if rule in CAP_HALT or rule == "over_per_transaction_cap":
            gap = money(quote["total_landed_cost"] - 500)
            choice = _best_swap(needs, picked, option_sets, gap)
            if choice is None or choice["ask"]:
                if rule == "over_per_transaction_cap":
                    question = (
                        _no_swap_question(quote["total_landed_cost"])
                        if choice is None
                        else _ask_question(quote["total_landed_cost"], choice)
                    )
                break
            picked[choice["index"]] = choice["product"]
            repair = {
                "need": needs[choice["index"]]["query"],
                "from_sku": choice["from_sku"],
                "to_sku": choice["product"]["id"],
                "saved": choice["saved"],
                "reason": choice["reason"],
            }
            repairs.append(repair)
            events.append(_revised(repair))
            continue
        break

    route, route_reason = choose_payment(lines)
    status = "NEEDS_INPUT" if question else policy["status"]
    cart_reason = f"Priced {rounds} basket{'s' if rounds != 1 else ''}. Final landed HK${quote['total_landed_cost']:.2f}."
    return {
        "status": status,
        "policy": policy,
        "quote": quote,
        "lines": lines,
        "repairs": repairs,
        "events": events,
        "question": question,
        "reply": reply,
        "payment_route": route,
        "payment_reason": route_reason,
        "cart_reason": cart_reason,
    }


def choose_payment(lines: list[dict], offers: list[dict] | None = None) -> tuple[str, str]:
    if offers is None:
        offers = _load_offers()
    totals: dict[str, float] = {}
    for line in lines:
        merchant = line["merchant"]
        totals[merchant] = money(totals.get(merchant, 0) + float(line["line_total"]))
    best = None
    for offer in offers:
        if offer.get("category") != "payment":
            continue
        method = str(offer.get("payment_method") or "").strip()
        retailer = str(offer.get("retailer") or "")
        if not method or retailer not in totals:
            continue
        fraction = _saving_fraction(str(offer.get("description") or ""))
        if fraction <= 0:
            continue
        hurdle = _hurdle(offer)
        if totals[retailer] + 0.001 < hurdle:
            continue
        saving = money(totals[retailer] * fraction)
        if best is None or saving > best[0]:
            best = (saving, method, str(offer.get("title") or method), retailer)
    if best is None:
        return "mastercard", "No payment offer matched this basket. Default route is mastercard."
    saving, method, title, retailer = best
    return (
        method,
        f"{title} at {retailer} via {method}. Estimated saving HK${saving:.2f} stays off the charge until person 4 applies the offer.",
    )


_DEFAULT_RANK = {"best_rating": 0, "highest_usage": 1, "cheap": 2}


def _sell_rank(item: dict, sell: str) -> int:
    if sell:
        return 0 if item.get("sell_point") == sell else 1
    return _DEFAULT_RANK.get(str(item.get("sell_point") or ""), 3)


def _prefer(options: list[dict], need: dict, methods, benefit_rank) -> list[dict]:
    """Sell point stays first. A card promotion wins only inside a close price band."""
    return rank_candidates(options, need, methods, benefit_rank)


def _draft(need: dict, product: dict, options: list[dict], methods=None, benefit_rank=None) -> dict:
    unit = money(product["price"])
    qty = int(need["qty"])
    return {
        "need": need["query"],
        "priority": int(need["priority"]),
        "sku": product["id"],
        "name": product["name"],
        "merchant": product["merchant"],
        "category": product["category"],
        "sell_point": product.get("sell_point") or "",
        "qty": qty,
        "unit_price": unit,
        "line_total": money(unit * qty),
        "image_url": product.get("image_url") or "",
        "product_reason": str(need.get("reason") or "").strip()
        or explain_pick(need, product, options, methods, benefit_rank),
        "merchant_reason": _merchant_reason(need, product, options),
    }


def _product_reason(need: dict, product: dict) -> str:
    sell = product.get("sell_point") or "unranked"
    asked = need.get("sell_point") or "no sell point"
    sentence = (
        f"{need['query']}: asked for {asked}. "
        f"{product['id']} is {sell} at HK${money(product['price']):.2f}."
    )
    if need.get("merchant") and asked not in {"", "no sell point"} and sell != asked:
        sentence += f" {need['merchant']} has no {asked} match, so this is the one that shop stocks."
    return sentence


def _merchant_reason(need: dict, product: dict, options: list[dict]) -> str:
    if need.get("merchant"):
        return (
            f"The basket is locked to {need['merchant']}. "
            f"{product['id']} is that shop's match at HK${money(product['price']):.2f}."
        )
    others = [item for item in options if item["id"] != product["id"]]
    if not others:
        return f"Only {product['merchant']} stocks this match."
    nxt = min(others, key=lambda item: float(item["price"]))
    return (
        f"{product['merchant']} has this pick at HK${money(product['price']):.2f}. "
        f"Next is {nxt['merchant']} {nxt['id']} at HK${money(nxt['price']):.2f}."
    )


def _score_merchant(catalog: list[dict], needs: list[dict], merchant: str) -> dict:
    blocked = {item.casefold() for item in CATEGORY_BLACKLIST}
    covered = 0
    payable_prices = []
    for need in needs:
        options = options_for(catalog, {**need, "merchant": merchant})
        if not options:
            continue
        covered += 1
        product = options[0]
        if str(product.get("category") or "").casefold() not in blocked:
            payable_prices.append(float(product["price"]) * int(need["qty"]))
    payable = len(payable_prices)
    return {
        "merchant": merchant,
        "covered": covered,
        "payable": payable,
        "landed": _estimate_landed(payable_prices) if payable else 10**9,
    }


def _estimate_landed(prices: list[float]) -> float:
    subtotal = money(sum(prices))
    shipping = 0.0 if subtotal >= 400 else 30.0
    return money(subtotal + shipping)


def _merchant_choice_reason(chosen: dict, scored: list[dict], named: str | None) -> str:
    bits = []
    for row in scored:
        landed = "none payable" if row["payable"] == 0 else f"est. HK${row['landed']:.2f}"
        bits.append(f"{row['merchant']} covers {row['covered']} ({row['payable']} payable, {landed})")
    if named:
        head = f"You asked for {chosen['merchant']}, so the basket stays at that shop."
    else:
        head = f"{chosen['merchant']} is the best single merchant."
    return (
        "Same-merchant request. Code compared shops by coverage, then payable items, then landed cost. "
        + head
        + " "
        + "; ".join(bits)
        + "."
    )


def _merge(drafts: list[dict], mall_lines: list[dict]) -> list[dict]:
    merged = []
    for draft, mall_line in zip(drafts, mall_lines):
        merged.append(
            {
                **draft,
                "sku": mall_line["sku"],
                "name": mall_line["name"],
                "merchant": mall_line["merchant"],
                "category": mall_line["category"],
                "unit_price": money(mall_line["unit_price"]),
                "qty": int(mall_line["qty"]),
                "line_total": money(mall_line["line_total"]),
            }
        )
    return merged


def _swap_illegal(needs, picked, option_sets, policy) -> dict | None:
    rule = policy.get("rule")
    for index, product in sorted(enumerate(picked), key=lambda pair: -needs[pair[0]]["priority"]):
        for alt in option_sets[index]:
            if alt["id"] == product["id"]:
                continue
            if rule == "category_blacklisted" and alt.get("category") == product.get("category"):
                continue
            if rule in {"merchant_blacklisted", "merchant_not_whitelisted"} and alt.get("merchant") == product.get("merchant"):
                continue
            saved = money((float(product["price"]) - float(alt["price"])) * needs[index]["qty"])
            picked[index] = alt
            return {
                "need": needs[index]["query"],
                "from_sku": product["id"],
                "to_sku": alt["id"],
                "saved": saved,
                "reason": f"Left {product['id']} because policy said {rule}.",
            }
    return None


def _best_swap(needs, picked, option_sets, gap: float) -> dict | None:
    silent = []
    asked = []
    for index, product in enumerate(picked):
        need = needs[index]
        for alt in option_sets[index]:
            if alt["id"] == product["id"]:
                continue
            saved = money((float(product["price"]) - float(alt["price"])) * need["qty"])
            if saved <= 0:
                continue
            same = alt.get("sell_point") == product.get("sell_point")
            proposal = {
                "index": index,
                "product": alt,
                "from_sku": product["id"],
                "saved": saved,
                "priority": need["priority"],
                "ask": bool(need["explicit"]) and not same,
                "reason": (
                    f"Swapped {need['query']} from {product['id']} to {alt['id']} "
                    f"to save HK${saved:.2f}."
                ),
            }
            if proposal["ask"]:
                asked.append(proposal)
            else:
                silent.append(proposal)
    silent.sort(key=lambda item: (-item["priority"], -item["saved"]))
    covering = [item for item in silent if item["saved"] + 0.001 >= gap]
    if covering:
        return covering[0]
    if silent:
        return silent[0]
    asked.sort(key=lambda item: (-item["priority"], -item["saved"]))
    if asked:
        return asked[0]
    return None


def _picked(round_no: int, lines: list[dict]) -> dict:
    labels = [f"{line['category']} {line['sku']}" for line in lines]
    thoughts = []
    for line in lines:
        thoughts.append(line.get("product_reason") or line["sku"])
    return {
        "event": "BASKET_PICKED",
        "status": "RECORDED",
        "reason": f"round {round_no} picks " + ", ".join(labels),
        "thought": "\n".join(thoughts),
    }


def _blocked_lines(lines: list[dict], round_events: list[dict]) -> list[dict]:
    dropped = []
    for line, event in zip(lines, round_events):
        rule = (event.get("result") or {}).get("rule") or ""
        if rule in LINE_HALT:
            dropped.append({**line, "_rule": rule})
    return dropped


def _join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _blacklist_reply(dropped: list[dict], kept: bool) -> str:
    categories = []
    merchants = []
    for line in dropped:
        rule = line.get("_rule") or ""
        if rule == "category_blacklisted":
            if line["category"] not in categories:
                categories.append(line["category"])
        elif line["merchant"] not in merchants:
            merchants.append(line["merchant"])
    parts = []
    if categories:
        verb = "is" if len(categories) == 1 else "are"
        parts.append(f"{_join_names(categories)} {verb} on the category blacklist")
    if merchants:
        verb = "is" if len(merchants) == 1 else "are"
        parts.append(f"{_join_names(merchants)} {verb} not allowed as a merchant")
    if not parts:
        parts.append("Some items are blocked by policy")
    items = ", ".join(f"{line['category']} {line['sku']} {line['name']}" for line in dropped)
    tail = "The other items are ready to pay." if kept else "Nothing in this request can be bought."
    return f"{'. '.join(parts)}, so I left them out: {items}. {tail}"


def _left_out(reply: str) -> dict:
    return {
        "event": "BASKET_REVISED",
        "status": "RECORDED",
        "reason": reply,
        "thought": "Blocked lines left the basket. The next check prices only the items that can be paid.",
    }


def _revised(repair: dict) -> dict:
    return {
        "event": "BASKET_REVISED",
        "status": "RECORDED",
        "reason": repair["reason"],
        "thought": "A line moved so the next policy check sees a new landed total.",
    }


def _ask_question(total: float, choice: dict) -> str:
    return (
        f"The best basket lands at HK${total:.2f}, over the HK$500 automatic cap. "
        f"{choice['reason']} That changes a sell point you asked for. "
        "Should I make that swap, or send this basket for approval?"
    )


def _no_swap_question(total: float) -> str:
    return (
        f"The best basket lands at HK${total:.2f}, over the HK$500 automatic cap. "
        "Nothing cheaper is on the shelf for these needs. "
        "Should I send this basket for approval?"
    )


def _saving_fraction(description: str) -> float:
    folded = description.casefold()
    zhe = re.search(r"(\d+)\s*折", folded)
    if zhe:
        pay = int(zhe.group(1))
        if 10 <= pay < 100:
            return money((100 - pay) / 100)
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%", folded)
    if percent:
        return money(float(percent.group(1)) / 100)
    return 0.0


def _hurdle(offer: dict) -> float:
    text = f"{offer.get('description') or ''} {offer.get('conditions') or ''}"
    amounts = [float(match.replace(",", "")) for match in re.findall(r"\$(\d[\d,]*)\+", text)]
    if not amounts:
        return 0.0
    return min(amounts)


def _load_offers() -> list[dict]:
    if not PROMO_PATH.exists():
        return []
    body = json.loads(PROMO_PATH.read_text(encoding="utf-8"))
    offers = body.get("offers")
    return offers if isinstance(offers, list) else []
