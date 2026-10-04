"""Bounded merchant allocation search for fixed quantities of equivalent products.

candidate_sets is a sequence aligned with lines; entries are catalogue IDs or
product dictionaries explicitly approved as alternatives by the caller. Known
package and servings mismatches are still rejected. Automatic alternatives need
an exact NFKC/case/whitespace-normalized name and identical known pack evidence.
Evaluators are Python-only hooks; the agent schema uses authoritative settlement_for.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Callable

from benefits import BENEFIT_KINDS, DEFAULT_RANK, settlement_for, choose_tender, current_rules, gift_lines

TOOL_NAME = "optimize_basket"
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Bounded search for lower effective basket cost with fixed quantities and explicit or exact-pack equivalents. Does not guarantee a global optimum.",
        "parameters": {
            "type": "object",
            "properties": {
                "lines": {"type": "array", "items": {"type": "object"}},
                "catalog": {"type": "array", "items": {"type": "object"}},
                "methods": {"type": "array", "items": {"type": "object"}},
                "rank": {"type": "array", "items": {"type": "string", "enum": list(BENEFIT_KINDS)}},
                "max_total": {"type": "number", "minimum": 0},
                "min_total": {"type": "number", "minimum": 0},
                "shipping": {"type": "array", "items": {"type": "number", "minimum": 0}, "minItems": 2, "maxItems": 2},
                "candidate_sets": {"type": "array", "items": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object"}]}}},
            },
            "required": ["lines", "catalog"],
            "additionalProperties": False,
        },
    },
}


def _money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def _normal(value) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _sku(row: dict) -> str:
    return str(row.get("sku") or row.get("id") or "")


def _pack(row: dict) -> tuple:
    fields = tuple(_normal(row.get(key)) for key in ("package", "package_size", "pack_size", "size", "servings", "servings_per_pack"))
    embedded = tuple(re.findall(r"\d+(?:\.\d+)?\s*(?:kg|mg|g|ml|l|lb|pcs?|pieces?|packs?)\b|\bx\s*\d+\b", _normal(row.get("name"))))
    return fields, embedded


def _compatible(base: dict, option: dict, explicit: bool) -> bool:
    left, right = _pack(base), _pack(option)
    if any(a and b and a != b for a, b in zip(left[0], right[0])):
        return False
    if left[1] and right[1] and left[1] != right[1]:
        return False
    if explicit:
        return True
    return bool(_normal(base.get("name"))) and _normal(base.get("name")) == _normal(option.get("name")) and left == right and (any(left[0]) or bool(left[1]))


def _quote(lines: list[dict], shipping: tuple[float, float]) -> dict:
    goods = _money(sum(row["line_total"] for row in lines))
    threshold, fee = shipping
    delivery = 0.0 if not lines or goods >= threshold - 1e-9 else _money(fee)
    return {"subtotal": goods, "shipping_fee": delivery, "tax": 0.0,
            "total_landed_cost": _money(goods + delivery), "currency": "HKD"}


def optimize_basket(
    lines: list[dict], catalog: list[dict], methods: list[dict] | None = None,
    rank: list[str] | None = None, max_total: float | None = None,
    min_total: float | None = None, shipping: tuple[float, float] = (400, 30),
    *, candidate_sets: list[list] | None = None, beam_width: int = 48,
    max_candidates: int = 16, max_evaluations: int = 4000, rounds: int = 4,
    offer_thresholds: dict[str, float] | None = None,
    quote_evaluator: Callable | None = None, settlement_evaluator: Callable | None = None,
    rules: dict | None = None, candidate_check: Callable | None = None,
) -> dict:
    """Return lines, quote, settlement and optimization metadata.

    Limits apply to charged total, before cashback. Infeasible searches return
    the initial basket with feasible=False, for the caller to handle. Quantities
    never change. Each beam move replaces one whole line, not individual units.
    Hooks accept (lines, shipping) and (lines, quote, methods, rank), respectively.
    Default delivery is basket-wide, matching meal_plan._quote. Thresholds only
    diversify search and never create offers. Explicit sets attest equivalence
    when pack evidence is missing; callers must supply servings for meal needs.
    """
    if min(beam_width, max_candidates, max_evaluations) < 1 or rounds < 0:
        raise ValueError("Search limits must be positive; rounds must be nonnegative")
    if len(shipping) != 2 or any(not math.isfinite(float(x)) or x < 0 for x in shipping):
        raise ValueError("shipping must contain a nonnegative threshold and fee")
    for bound in (min_total, max_total):
        if bound is not None and (not math.isfinite(float(bound)) or bound < 0):
            raise ValueError("Budget limits must be finite and nonnegative")
    if min_total is not None and max_total is not None and min_total > max_total:
        raise ValueError("min_total exceeds max_total")
    if candidate_sets is not None and len(candidate_sets) != len(lines):
        raise ValueError("candidate_sets must align with lines")
    snapshot = current_rules(rules)
    if any(line.get("is_gift") for line in lines):
        raise ValueError("Optimizer input must contain purchased lines only")
    thresholds = offer_thresholds if offer_thresholds is not None else (
        {row["merchant"]: row["threshold"] for row in snapshot["promotions"] if row["enabled"]}
        if snapshot is not None else {"Watsons": 300.0, "PARKnSHOP": 300.0})
    policy_results = {}

    def eligible(row, qty):
        if candidate_check is None:
            return True
        key = (_sku(row), str(row.get("merchant") or ""), qty)
        if key not in policy_results:
            verdict = candidate_check(dict(row), int(qty))
            if not isinstance(verdict, dict) or type(verdict.get("eligible")) is not bool:
                raise ValueError("candidate_check must return {eligible: bool, ...policy evidence}")
            policy_results[key] = verdict
        return policy_results[key]["eligible"]
    index, names = {}, {}
    for row in catalog:
        sku = _sku(row)
        if sku:
            index[sku] = row
        if candidate_sets is None:
            names.setdefault(_normal(row.get("name")), []).append(row)
    pools, counts = [], []
    for i, line in enumerate(lines):
        qty = line.get("qty", 1)
        if isinstance(qty, bool) or int(qty) != qty or qty <= 0:
            raise ValueError("Each quantity must be a positive integer")
        base = {**index.get(_sku(line), {}), **line}
        # Catalog price is authoritative when the SKU exists in the live shelf.
        base["price"] = index[_sku(line)]["price"] if _sku(line) in index else line.get("unit_price", base.get("price", 0))
        explicit = candidate_sets is not None
        raw = candidate_sets[i] if explicit else names.get(_normal(base.get("name")), [])
        eligible(base, qty)
        options = [base]
        seen = {(_sku(base), str(base.get("merchant") or ""))}
        for candidate in raw:
            option = candidate if isinstance(candidate, dict) else index.get(str(candidate))
            if option is None:
                raise ValueError(f"Unknown alternative: {candidate}")
            key = (_sku(option), str(option.get("merchant") or ""))
            if key in seen or not _compatible(base, option, explicit):
                continue
            if not eligible(option, qty):
                continue
            if option.get("in_stock") is False:
                continue
            if option.get("stock") is not None and float(option["stock"]) < qty:
                continue
            seen.add(key)
            options.append(option)
        def price(row):
            value = float(row.get("price", row.get("unit_price", 0)))
            if not math.isfinite(value) or value < 0:
                raise ValueError("Prices must be finite and nonnegative")
            return value
        options[1:] = sorted(options[1:], key=lambda row: (price(row), _sku(row)))
        price(base)
        counts.append(len(options) - 1)
        # Round-robin merchants prevents one cheap shop consuming the entire cap.
        buckets = {}
        for option in options[1:]:
            buckets.setdefault(str(option.get("merchant") or "Shop"), []).append(option)
        kept = [base]
        while buckets and len(kept) < max_candidates:
            for merchant in list(buckets):
                if len(kept) >= max_candidates:
                    break
                kept.append(buckets[merchant].pop(0))
                if not buckets[merchant]:
                    del buckets[merchant]
        pools.append(kept)
    initial = tuple(0 for _ in pools)
    cache = {}
    exhausted = False
    order = list(dict.fromkeys([kind for kind in (rank or DEFAULT_RANK) if kind in BENEFIT_KINDS] + list(DEFAULT_RANK)))

    def evaluate(state):
        nonlocal exhausted
        if state in cache:
            return cache[state]
        if len(cache) >= max_evaluations:
            exhausted = True
            return None
        selected = []
        for line, pool, choice in zip(lines, pools, state):
            product = pool[choice]
            unit = _money(product.get("price", product.get("unit_price", 0)))
            selected.append({**line, **{k: v for k, v in product.items() if k not in {"qty", "line_total", "unit_price"}},
                             "sku": _sku(product), "qty": int(line.get("qty", 1)),
                             "unit_price": unit, "line_total": _money(unit * int(line.get("qty", 1)))})
        quote = (quote_evaluator or _quote)(selected, shipping)
        settlement = (settlement_evaluator(selected, quote, methods, rank) if settlement_evaluator
                      else settlement_for(selected, quote, methods, rank, rules=snapshot))
        charged = _money(settlement["total"])
        benefits = {kind: sum(float(b.get("amount") or 0) for b in settlement.get("benefits", []) if b.get("kind") == kind) for kind in BENEFIT_KINDS}
        effective = _money(charged - benefits["cash"])
        quantities = {}
        for row in selected:
            quantities[row["sku"]] = quantities.get(row["sku"], 0) + row["qty"]
        available = all(row.get("in_stock") is not False and (
            row.get("stock") is None or float(row["stock"]) >= quantities[row["sku"]]
        ) for row in selected)
        payable = all(choose_tender(str(row.get("merchant") or "Shop"), row["line_total"], methods, rank, rules=snapshot)["route"]
                      for row in selected)
        policy_ok = all(eligible(row, row["qty"]) for row in selected)
        feasible = policy_ok and available and payable and (max_total is None or charged <= max_total + 1e-9) and (min_total is None or charged >= min_total - 1e-9)
        gap = max(0, charged - max_total) if max_total is not None else 0
        gap += max(0, min_total - charged) if min_total is not None else 0
        merchants = {row.get("merchant") or "Shop" for row in selected}
        key = (not feasible, _money(gap), effective, tuple(-benefits[k] for k in order if k != "cash"), len(merchants), state)
        subtotals = {m: _money(sum(row["line_total"] for row in selected if (row.get("merchant") or "Shop") == m)) for m in merchants}
        signature = (tuple(sorted(merchants)), tuple(sorted((m, subtotals.get(m, 0) >= threshold) for m, threshold in thresholds.items())))
        result = {"lines": selected + gift_lines(selected, snapshot), "quote": quote, "settlement": settlement, "effective": effective,
                  "feasible": feasible, "key": key, "signature": signature}
        cache[state] = result
        return result

    evaluate(initial)
    seeds = [initial]
    merchants = sorted({str(p.get("merchant") or "Shop") for pool in pools for p in pool})
    for merchant in merchants:
        choices = [[j for j, p in enumerate(pool) if (p.get("merchant") or "Shop") == merchant] for pool in pools]
        if all(choices):
            seeds.append(tuple(group[0] for group in choices))
        if merchant in thresholds:
            seeds.append(tuple(group[0] if group else 0 for group in choices))
    for state in seeds:
        evaluate(state)

    def prune(states):
        ranked = sorted(set(states), key=lambda s: cache[s]["key"])
        diverse, signatures = [], set()
        for state in ranked:
            signature = cache[state]["signature"]
            if signature not in signatures:
                diverse.append(state)
                signatures.add(signature)
        reserved = diverse[:max(1, beam_width // 2)]
        return list(dict.fromkeys(reserved + ranked))[:beam_width]

    beam = prune(cache)
    completed_rounds = 0
    for _ in range(rounds):
        trials = list(beam)
        for state in beam:
            for i, pool in enumerate(pools):
                for j in range(len(pool)):
                    trial = state[:i] + (j,) + state[i + 1:]
                    if evaluate(trial) is not None:
                        trials.append(trial)
                    if exhausted:
                        break
                if exhausted:
                    break
            if exhausted:
                break
        next_beam = prune(trials)
        completed_rounds += 1
        if next_beam == beam or exhausted:
            break
        beam = next_beam
    feasible = [row for row in cache.values() if row["feasible"]]
    start = cache[initial]
    best = min(feasible, key=lambda row: row["key"]) if feasible else start
    explanation = (f"Bounded beam search evaluated {len(cache)} allocations; no global optimum is claimed. "
                   f"Effective cost is charged total minus cash cashback: HK${start['effective']:.2f} initially, "
                   f"HK${best['effective']:.2f} selected. Quantities are unchanged; ranked noncash benefits "
                   "and then fewer merchants break cost ties.")
    multi_quantity_lines = [i for i, line in enumerate(lines) if line.get("qty", 1) > 1]
    if multi_quantity_lines:
        explanation += " Each line's full quantity stays at one merchant; splitting units within a line is not searched."
    if not feasible:
        explanation += " No evaluated allocation meets the charged-total spend band; the initial basket is returned."
    return {"lines": best["lines"], "quote": best["quote"], "settlement": best["settlement"],
            "optimization": {"tool": TOOL_NAME, "search": "bounded_beam", "global_optimum_guaranteed": False,
                             "rules_version": snapshot["version"] if snapshot is not None else None,
                             "candidate_policy_results": [{"sku": key[0], "merchant": key[1], "qty": key[2], **value} for key, value in policy_results.items()],
                             "feasible": bool(feasible), "alternatives_counts": counts,
                             "quantity_split_supported": False, "multi_quantity_line_indices": multi_quantity_lines,
                             "retained_alternatives_counts": [len(pool) - 1 for pool in pools],
                             "initial_effective_cost": start["effective"], "selected_effective_cost": best["effective"],
                             "evaluations": len(cache), "evaluation_limit_reached": exhausted,
                             "beam_width": beam_width, "max_candidates": max_candidates,
                             "max_evaluations": max_evaluations, "rounds_completed": completed_rounds,
                             "explanation": explanation}}
