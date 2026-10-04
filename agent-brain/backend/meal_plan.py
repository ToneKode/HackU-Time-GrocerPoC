"""Meal-plan optimiser for sentences such as
"max 500 HKD, spend at least 80% of the cap, food for 5 days for a family of 3,
more categories like protein, fruit and main-dish ingredients".

Everything numeric is computed here, deterministically, from:
  * the shopper's sentence (cap, minimum spend, days, family size, food groups),
  * the catalogue rows (price, merchant, name, category),
  * the shopper's CONNECTED payment methods and benefit ranking (profile),
  * benefits.quote_tender / settlement_for (cashback, points, miles, shop promos).

The language model is never asked to add prices or pick products. It may only
add wording on top of this plan (openrouter.enrich_meal_plan), and that output
is validated against the basket before it is shown.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from benefits import (
    BENEFIT_KINDS,
    DEFAULT_RANK,
    _rank_order,
    connected_methods,
    quote_tender,
    settlement_for,
)
from policy_rules import PER_TRANSACTION_CAP, WHITELIST

# Shop-wide offers that start at a goods subtotal (mirrors benefits.quote_tender:
# Watsons 15% off and PARKnSHOP 10% off from HK$300). The optimiser builds an extra
# "anchor" basket per offer: enough of that shop to unlock it, the rest from any shop.
OFFER_THRESHOLDS = {"Watsons": 300.0, "PARKnSHOP": 300.0}
# Baskets whose servings coverage is within this of the best basket count as feeding
# the family equally well, so the shopper's benefit ranking decides between them.
NUTRITION_TOLERANCE = 0.06

# --------------------------------------------------------------------------
# Food groups
# --------------------------------------------------------------------------

GROUPS = {
    # key: (label, servings per person per day, grams or ml per serving)
    "staple": ("main-dish staples (rice, noodles, pasta)", 2.0, 80.0),
    "protein": ("protein (meat, fish, eggs, tofu)", 2.0, 120.0),
    "vegetable": ("vegetables", 1.5, 80.0),
    "fruit": ("fruit", 1.0, 150.0),
    "dairy": ("dairy and soy milk", 1.0, 250.0),
    "drinks": ("drinks", 1.0, 330.0),
    "snacks": ("snacks", 0.5, 30.0),
    "condiment": ("soup bases and condiments", 1.0, 20.0),
}
DEFAULT_GROUPS = ["staple", "protein", "vegetable", "fruit", "drinks", "snacks"]
VARIETY_EXTRA = ["vegetable", "dairy", "drinks"]
BENEFIT_LABELS = {
    "cash": "cashback",
    "asiamiles": "Asia Miles",
    "membership_points": "membership points",
    "loyalty_points": "loyalty points",
}

_EDIBLE = frozenset({"food", "beverages", "snacks", "rice & noodles", "frozen food", "pantry"})

_ASK_WORDS = (
    ("staple", r"main[\s-]*d[ia]sh|main course|staple|carb|\brice\b|noodle|pasta|grain|bread"),
    ("protein", r"protein|\bmeat|chicken|beef|pork|\bfish|seafood|\beggs?\b|tofu"),
    ("vegetable", r"\bveg|vegetable|greens|salad"),
    ("fruit", r"fruit"),
    ("dairy", r"dairy|\bmilk|yogh?urt|cheese|soy ?milk"),
    ("drinks", r"\bdrinks?\b|beverage|juice|\bwater\b|\btea\b"),
    ("snacks", r"snack|chips|biscuit|cookie|dessert"),
    ("condiment", r"soup base|broth|seasoning|condiment|sauce"),
)

_NON_FOOD = re.compile(
    r"lotion|moistur|shampoo|soap|detergent|cleanser|tissue|toothpaste|diaper|"
    r"\bbeer\b|wine|whisk|vodka|\bsake\b|soju|liqueur|champagne|brandy|\bgin\b|\brum\b|alcohol|\bice rose\b",
    re.IGNORECASE,
)
_DESSERT = re.compile(
    r"ice[ -]?cream|ice bar|gelato|sorbet|popsicle|tong yuen|choco|lollipop|candy|jelly|"
    r"\bcake\b(?! - stick)|custard|cookies? & cream|rocky road|tongyuen|pepero|wafer|biscuit|cookie|"
    r"marshmallow|gummy|pudding|mochi",
    re.IGNORECASE,
)
_DRINK_ONLY = re.compile(r"milk tea|coffee|soft drink|carbonated|\bsoda\b|\bcola\b|\btea\b", re.IGNORECASE)
_STAPLE = re.compile(
    r"\brice\b|noodl|ramen|udon|soba|pasta|spaghetti|fusilli|linguine|penne|macaroni|vermicelli|"
    r"\bbread\b|\boats?\b|oatmeal|cereal|congee|dumpling|pizza|tangmyun|chajang|jja jang|\bmen\b",
    re.IGNORECASE,
)
_PROTEIN = re.compile(
    r"chicken|beef|pork|\bfish|tuna|salmon|sardine|mackerel|\beggs?\b|tofu|bean curd|shrimp|prawn|scallop|"
    r"abalone|\bham\b|sausage|luncheon|\bmeat|lamb|mutton|\bduck|quail|mince|drumstick|drumette|"
    r"\bwings?\b|\bcod\b|squid|crab|\bdace\b|topshell|steak|nugget|karaage|fillet|jerky|\bnuts?\b|almond|peanut",
    re.IGNORECASE,
)
_FRUIT = re.compile(
    r"fruit|apple|banana|orange|mango|pineapple|pinapple|peach|grape|berry|berries|\bdates?\b|kiwi|lemon|"
    r"\bpears?\b|lychee|mandarin|tangerine|raisin|prune|\bplum|melon|cherry(?! blossom)|coconut|guava",
    re.IGNORECASE,
)
_VEG = re.compile(
    r"vegetable|veggie|\bcorn\b|spinach|broccoli|carrot|mushroom|seaweed|tomato|kimchi|cabbage|lettuce|"
    r"onion|bean sprout|\bpeas?\b|\bbeans\b|potato(?! chip| crisp)|pumpkin|beetroot|bamboo shoot",
    re.IGNORECASE,
)
_DAIRY = re.compile(r"\bmilk\b|yogh?urt|cheese|soya? ?bean milk|soy(?:a)? milk|soyabean|calcium", re.IGNORECASE)
_CONDIMENT = re.compile(r"\bsugar\b|\bsalt\b|sauce|vinegar|seasoning|ketchup|mayo|\bstock\b", re.IGNORECASE)

_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l|lb)(?![a-z])", re.IGNORECASE)
_MULT = re.compile(
    r"(?:x|\*|×)\s*(\d{1,2})(?!\d)(?:\s*(?:packs?|pk|p|bottles?|cans?|bags?)(?![a-z]))?|(\d{1,2})[\s-]*(?:packs?|pk|p|bottles?|cans?|bags?)(?![a-z])",
    re.IGNORECASE,
)
_PIECES = re.compile(r"(\d{1,3})\s*(?:pcs|pc|pieces|s|'s)(?![a-z])", re.IGNORECASE)


def classify(item: dict) -> str | None:
    """Food group of one catalogue row, from its category and name. None = not a meal item."""
    category = str(item.get("category") or "").casefold()
    if category not in _EDIBLE:
        return None
    name = str(item.get("name") or "")
    if _NON_FOOD.search(name):
        return None
    if re.search(r"soup base|broth|bouillon|seasoning|\bstock\b|vinegar|ketchup|mayonnaise", name, re.IGNORECASE) or (re.search(r"sauce", name, re.IGNORECASE) and not re.search(r"\bin\b|\bwith\b|flavou?r", name, re.IGNORECASE)):
        return "condiment"
    if category == "beverages":
        if _DRINK_ONLY.search(name):
            return "drinks"
        if _DAIRY.search(name):
            return "dairy"
        if re.search(r"tomato|carrot|vegetable|beetroot", name, re.IGNORECASE):
            return "vegetable"
        if _FRUIT.search(name) and re.search(r"juice|100%|nectar", name, re.IGNORECASE):
            return "fruit"
        return "drinks"
    if category == "snacks":
        if re.search(r"dried|raisin|prune|\bdates?\b|fruit", name, re.IGNORECASE) and not _DESSERT.search(name):
            return "fruit"
        if _DESSERT.search(name) or re.search(r"chip|crisp|cracker|stick|\bbar\b|snack", name, re.IGNORECASE):
            return "snacks"
        if re.search(r"mixed nuts|\bnuts\b|roasted (?:almond|peanut|cashew)|jerky|cashew|walnut|pistachio", name, re.IGNORECASE):
            return "protein"
        return "snacks"
    if category == "rice & noodles":
        return "staple"
    # food / frozen food / pantry
    if _DESSERT.search(name) or re.search(r"\bthins\b|\bchips?\b|crisps?\b|popcorn", name, re.IGNORECASE):
        return "snacks"
    if re.search(r"broth|soup base|\bstock\b|bouillon|seasoning|\boil\b(?! flav)|\bflour\b|vinegar", name, re.IGNORECASE):
        return None
    if _STAPLE.search(name):
        return "staple"
    if _PROTEIN.search(name):
        return "protein"
    if _FRUIT.search(name):
        return "fruit"
    if _VEG.search(name):
        return "vegetable"
    if _DAIRY.search(name):
        return "dairy"
    if _CONDIMENT.search(name):
        return None
    return None


def servings(item: dict, group: str) -> tuple[float, str]:
    """Estimated servings in one pack, and the words used to get there."""
    name = str(item.get("name") or "")
    name = re.sub(r"\[(?:max|limit)[^]]*\]", "", name, flags=re.IGNORECASE)
    _label, _per_day, per_serving = GROUPS[group]
    if group == "condiment":
        return 1.0, "1 household supply of seasoning; not counted as a meal serving"
    size = None
    unit = ""
    for match in _SIZE.finditer(name):
        value, raw = float(match.group(1)), match.group(2).casefold()
        grams = value * 1000 if raw in {"kg", "l"} else value * 453.6 if raw == "lb" else value
        size, unit = grams, ("ml" if raw in {"ml", "l"} else "g")
        break
    count = 1
    count_words = []
    for match in _MULT.finditer(name):
        number = int(match.group(1) or match.group(2))
        if 1 < number <= 48:
            count *= number
            count_words.append(match.group(0).strip())
    if count > 60:
        count = 60
    pieces = 0
    piece_match = _PIECES.search(name)
    if piece_match:
        pieces = int(piece_match.group(1))
    if group == "protein" and re.search(r"\beggs?\b", name, re.IGNORECASE) and (pieces or count > 1):
        eggs = (pieces or 1) * count if pieces else count
        total = eggs / 2.0
        basis = f"{eggs} eggs at 2 eggs per serving"
    elif group == "staple" and pieces and not size:
        total = float(pieces * count)
        basis = f"{pieces * count} portions in the pack"
    elif group == "staple" and re.search(r"noodl|ramen|udon|soba", name, re.IGNORECASE) and count > 1:
        total = float(count)
        basis = f"{count} packs of noodles, 1 serving each"
    elif size:
        per = 75.0 if group == "staple" and re.search(r"\brice\b", name, re.IGNORECASE) else per_serving
        if group == "staple" and re.search(r"noodle|ramen|udon", name, re.IGNORECASE) and size < 200:
            total = float(count)
            basis = f"{count} pack(s) of noodles, 1 serving each"
        else:
            total = size * count / per
            basis = f"{_fmt_qty(size)}{unit}" + (f" x {count}" if count > 1 else "") + f" at ~{per:.0f}{unit} per serving"
    elif pieces > 1:
        total = float(pieces) * count / (2.0 if group == "protein" else 1.0)
        basis = f"{pieces} pieces" + (f" x {count}" if count > 1 else "") + (" at 2 pieces per serving" if group == "protein" else ", 1 serving each")
    elif group == "staple" and re.search(r"\brice\b", name, re.IGNORECASE) and float(item.get("price") or 0) > 30:
        total = 20.0 * count
        basis = (f"{count} bags" if count > 1 else "1 bag") + " of rice with no weight in the name, assumed ~1.5kg (20 servings) per bag"
    elif count > 1:
        total = float(count)
        basis = f"pack of {count} ({', '.join(count_words)}), 1 serving each"
    else:
        default = {"staple": 1.0, "protein": 2.0, "vegetable": 2.0, "fruit": 2.0, "dairy": 1.0, "drinks": 1.0, "snacks": 2.0, "condiment": 10.0}[group]
        if group == "staple" and re.search(r"\brice\b", name, re.IGNORECASE) and float(item.get("price") or 0) > 30:
            default = 20.0
        total = default
        basis = f"no pack size in the name, assumed {default:g} serving(s)"
    factor, why = _quality(item, group)
    if factor < 1.0:
        total *= factor
        basis += f"; counted at {factor * 100:.0f}% because {why}"
    total = max(0.1, total)
    return round(total, 1), basis


def _quality(item: dict, group: str) -> tuple[float, str]:
    """Juice is not whole fruit and nuts are not a main protein: they count for less."""
    name = str(item.get("name") or "")
    category = str(item.get("category") or "").casefold()
    if group in {"fruit", "vegetable"} and (category == "beverages" or re.search(r"juice", name, re.IGNORECASE)):
        return 0.5, "juice is not whole fruit or vegetables"
    if group == "protein" and category == "snacks":
        return 0.5, "nuts are a side protein, not a main dish"
    if group == "fruit" and category == "snacks":
        return 0.6, "dried fruit is a snack portion"
    return 1.0, ""


def _fmt_qty(value: float) -> str:
    return f"{value:g}"


# --------------------------------------------------------------------------
# Reading the sentence
# --------------------------------------------------------------------------

_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "a couple": 2, "couple": 2,
}
_NUM = r"(\d+(?:\.\d+)?)"
_NOT_MONEY_AFTER = re.compile(r"^\s*(?:%|percent|days?|weeks?|people|persons?|ppl|members?|pax|kids?|adults?)", re.IGNORECASE)
_MAX_WORDS = re.compile(
    r"(?:maximum|\bmax\b|budget|\bcap\b|\blimit\b|\bunder\b|\bwithin\b|no more than|not more than|"
    r"up to|don't spend more than|do not spend more than|at most)",
    re.IGNORECASE,
)
_MIN_WORDS = re.compile(r"(?:at least|minimum|\bmin\b|no less than|not less than)", re.IGNORECASE)


@dataclass
class MealRequest:
    days: int = 7
    days_source: str = "default"
    family: int = 1
    family_source: str = "default"
    max_total: float | None = None
    max_source: str = ""
    min_total: float | None = None
    min_source: str = ""
    min_pct: float | None = None
    groups: list[str] = field(default_factory=list)
    asked_groups: list[str] = field(default_factory=list)
    variety: bool = False
    many: bool = False
    wants_cash: bool = False
    merchants: list[str] = field(default_factory=list)

    @property
    def variety_target(self) -> int:
        """Distinct products wanted per food group: 3 for "as many as possible", 2 for a
        variety request or any plan of 3+ days (nobody wants one rice for a week), else 1."""
        if self.many:
            return 3
        if not self.asked_groups:
            return 2
        return 2 if self.variety or self.days >= 3 else 1

    @property
    def person_days(self) -> int:
        return self.days * self.family

    def as_dict(self) -> dict:
        return {
            "days": self.days,
            "days_source": self.days_source,
            "family_size": self.family,
            "family_source": self.family_source,
            "max_total": self.max_total,
            "max_source": self.max_source,
            "min_total": self.min_total,
            "min_pct": self.min_pct,
            "min_source": self.min_source,
            "groups": list(self.groups),
            "asked_groups": list(self.asked_groups),
            "variety": self.variety,
            "variety_target": self.variety_target,
            "merchants": list(self.merchants),
        }


def _number_after(text: str, start: int, window: int = 40) -> tuple[float, int, int] | None:
    """First number within `window` chars after `start` that is not a percent/day/person count."""
    for match in re.finditer(_NUM, text[start : start + window]):
        tail = text[start + match.end() : start + match.end() + 12]
        if _NOT_MONEY_AFTER.match(tail):
            return None
        return float(match.group(1)), start + match.start(), start + match.end()
    return None


def parse_request(intent: str) -> MealRequest:
    text = " ".join(intent.split())
    low = text.casefold()
    req = MealRequest()

    day_text = re.sub(r"\b(" + "|".join(_WORD_NUM) + r")(?=\s+days?\b)",
                      lambda match: str(_WORD_NUM[match.group(1)]), low)
    match = re.search(r"(\d+)\s*(?:-|\s)?\s*days?\b", day_text)
    if match:
        req.days, req.days_source = max(1, min(60, int(match.group(1)))), f"'{match.group(0)}'"
    else:
        weeks = re.search(r"(\d+|a|one|two)\s*weeks?\b", low)
        if weeks:
            word = weeks.group(1)
            n = int(word) if word.isdigit() else {"a": 1, "one": 1, "two": 2}[word]
            req.days, req.days_source = 7 * n, f"'{weeks.group(0)}'"

    family_patterns = (
        r"family (?:with (?:a )?size of|size of|of|with)\s*(\d+|[a-z]+)",
        r"family size (?:of |is )?(\d+|[a-z]+)",
        r"(\d+|[a-z]+)[\s-]*(?:people|persons|person|ppl|members|pax)\b",
        r"for (\d+|two|three|four|five|six)\b(?! days?| weeks?| hkd| dollars| adults?| kids?| child)",
    )
    for pattern in family_patterns:
        found = re.search(pattern, low)
        if not found:
            continue
        raw = found.group(1)
        value = int(raw) if raw.isdigit() else _WORD_NUM.get(raw)
        if value and 1 <= value <= 20:
            req.family, req.family_source = value, f"'{found.group(0)}'"
            break

    if req.family_source == "default":
        household = re.findall(r"(\d+|one|two|three|four|five|six)\s*(?:adults?|kids?|child(?:ren)?)\b", low)
        if household:
            people = sum(int(raw) if raw.isdigit() else _WORD_NUM[raw] for raw in household)
            if 1 <= people <= 20:
                req.family, req.family_source = people, "adult and child counts"

    # Maximum: a keyword followed by an amount (not a %, day or person count).
    for keyword in _MAX_WORDS.finditer(low):
        if _MIN_WORDS.search(low[max(0, keyword.start() - 12) : keyword.start()]):
            continue
        hit = _number_after(low, keyword.end())
        if hit:
            req.max_total, req.max_source = round(hit[0], 2), f"'{text[keyword.start():hit[2]].strip()}'"
            break
    if req.max_total is None:
        money = re.search(r"(?:hk\$|hkd|\$)\s*" + _NUM + r"|" + _NUM + r"\s*(?:hkd|hk\$|dollars)", low)
        if money and not _MIN_WORDS.search(low[max(0, money.start() - 25) : money.start()]):
            value = float(money.group(1) or money.group(2))
            req.max_total, req.max_source = round(value, 2), f"'{text[money.start():money.end()].strip()}'"

    # Minimum: an amount, or a percentage of the cap.
    for keyword in _MIN_WORDS.finditer(low):
        window = low[keyword.end() : keyword.end() + 45]
        pct = re.search(_NUM + r"\s*(?:%|percent)", window)
        amount = re.search(r"(?:hk\$|hkd|\$)?\s*" + _NUM + r"(?![\d.])(?!\s*(?:%|percent|days?|people))", window)
        if pct and (not amount or pct.start(1) <= amount.start(1)):
            req.min_pct = float(pct.group(1)) / 100.0
            req.min_source = f"'{text[keyword.start(): keyword.end() + pct.end()].strip()}'"
            break
        if amount:
            req.min_total = round(float(amount.group(1)), 2)
            req.min_source = f"'{text[keyword.start(): keyword.end() + amount.end()].strip()}'"
            break
    if req.min_pct is not None and req.max_total is not None:
        req.min_total = round(req.max_total * req.min_pct, 2)

    asked = []
    for group, pattern in _ASK_WORDS:
        found = re.search(pattern, low)
        if found:
            asked.append((found.start(), group))
    asked.sort()
    req.asked_groups = [group for _pos, group in asked]
    if re.search(r"\bingredients?\b", low) and not req.asked_groups:
        req.asked_groups = ["staple", "protein", "vegetable"]
    req.variety = bool(
        re.search(r"more (?:food )?categor|variety|different|etc\b|and so on|balanced|mix\b", low)
    )
    req.many = bool(re.search(r"as possible|as many|many different|lots of different", low))
    groups = list(req.asked_groups) or list(DEFAULT_GROUPS)
    if req.variety:
        for extra in VARIETY_EXTRA:
            if extra not in groups:
                groups.append(extra)
    req.groups = groups
    req.wants_cash = "cash back" in low or "cashback" in low
    req.merchants = [merchant for merchant in WHITELIST if merchant.casefold() in low]
    return req


# --------------------------------------------------------------------------
# Money helpers
# --------------------------------------------------------------------------


def _money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def _landed(goods: float, shipping: tuple[float, float]) -> float:
    threshold, fee = shipping
    return _money(goods + (0.0 if goods >= threshold - 1e-9 else fee))


@dataclass
class _Row:
    item: dict
    group: str
    servings: float
    basis: str
    qty: int = 1

    @property
    def sku(self) -> str:
        return str(self.item["id"])

    @property
    def price(self) -> float:
        return float(self.item["price"])

    @property
    def per_serving(self) -> float:
        return self.price / max(self.servings, 0.1)


def _lines_of(rows: list[_Row]) -> list[dict]:
    return [
        {
            "sku": row.sku,
            "name": row.item.get("name"),
            "merchant": row.item.get("merchant"),
            "category": row.item.get("category"),
            "qty": row.qty,
            "unit_price": _money(row.price),
            "line_total": _money(row.price * row.qty),
        }
        for row in rows
    ]


def _quote(rows: list[_Row], shipping: tuple[float, float]) -> dict:
    goods = _money(sum(row.price * row.qty for row in rows))
    landed = _landed(goods, shipping)
    return {
        "subtotal": goods,
        "shipping_fee": _money(landed - goods),
        "tax": 0.0,
        "total_landed_cost": landed,
        "currency": "HKD",
    }


def benefit_value(settlement: dict, kind: str) -> float:
    total = 0.0
    if kind == "cash":
        total += float(settlement.get("discount") or 0)
    for benefit in settlement.get("benefits") or []:
        if benefit.get("kind") == kind:
            total += float(benefit.get("amount") or 0)
    return _money(total)


# --------------------------------------------------------------------------
# The optimiser
# --------------------------------------------------------------------------


@dataclass
class _Plan:
    name: str
    merchants: list[str]
    rows: list[_Row]
    settlement: dict
    quote: dict
    coverage: dict
    meets_band: bool
    covered_groups: int
    nutrition: float
    benefit_key: tuple
    blocked: str = ""


def _pool(catalog: list[dict], merchants: set[str] | None, ceiling: float, groups: list[str]) -> dict[str, list[_Row]]:
    pool: dict[str, list[_Row]] = {group: [] for group in groups}
    seen = set()
    for item in catalog:
        if item.get("in_stock") is False:
            continue
        merchant = str(item.get("merchant") or "")
        if merchant not in WHITELIST or (merchants is not None and merchant not in merchants):
            continue
        try:
            price = float(item.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0 or price > ceiling:
            continue
        group = classify(item)
        if group not in pool:
            continue
        sku = str(item.get("id") or "")
        if not sku or sku in seen:
            continue
        seen.add(sku)
        count, basis = servings(item, group)
        pool[group].append(_Row(item=item, group=group, servings=count, basis=basis))
    for rows in pool.values():
        rows.sort(key=lambda row: (row.per_serving, row.price, row.sku))
    return pool


def _needs(req: MealRequest) -> dict[str, float]:
    return {
        group: (max(1, math.ceil(req.person_days / 30)) if group == "condiment"
                else GROUPS[group][1] * req.person_days)
        for group in req.groups
    }


def _have(rows: list[_Row]) -> dict[str, float]:
    have: dict[str, float] = {}
    for row in rows:
        have[row.group] = have.get(row.group, 0.0) + row.servings * row.qty
    return have


def _fill(
    pool: dict[str, list[_Row]],
    req: MealRequest,
    ceiling: float,
    minimum: float | None,
    shipping: tuple[float, float],
    methods: list[dict],
    rank: list[str],
    seed: list[_Row] | None = None,
) -> list[_Row]:
    need = _needs(req)
    chosen: list[_Row] = [
        _Row(item=row.item, group=row.group, servings=row.servings, basis=row.basis, qty=row.qty)
        for row in seed or []
    ]
    by_sku: dict[str, _Row] = {row.sku: row for row in chosen}
    variety_target = req.variety_target

    def goods_after(extra: float) -> float:
        return sum(row.price * row.qty for row in chosen) + extra

    def fits(price: float) -> bool:
        return _landed(goods_after(price), shipping) <= ceiling + 1e-6

    def add(row: _Row) -> None:
        if row.sku in by_sku:
            by_sku[row.sku].qty += 1
        else:
            fresh = _Row(item=row.item, group=row.group, servings=row.servings, basis=row.basis, qty=1)
            chosen.append(fresh)
            by_sku[fresh.sku] = fresh

    def best_move(group: str, prefer_new: bool) -> _Row | None:
        rows = pool.get(group) or []
        have = _have(chosen).get(group, 0.0)
        target = need[group]
        if group == "condiment":
            # One bottle/base usually lasts the whole planning period.
            cap = max(1, math.ceil(req.person_days / 30))
            if sum(row.qty for row in chosen if row.group == group) >= cap:
                return None
        elif have >= target - 1e-6:
            return None
        candidates = [row for row in rows if fits(row.price)]
        if not candidates:
            return None
        new = [row for row in candidates if row.sku not in by_sku]
        if prefer_new:
            if not new:
                return None
            candidates = new
        elif new and group != "condiment":
            # Prefer another suitable food before repeating a selected product.
            candidates = new
        floor = min(row.per_serving for row in candidates)
        close = [row for row in candidates if row.per_serving <= floor * 1.08 + 0.01]

        def move_key(row: _Row) -> tuple:
            tender = choose_line_tender(str(row.item.get("merchant")), row.price, methods, rank)
            rates = tender.get("rates") or {}
            return (max(0.0, have + row.servings - target),
                    tuple(-float(rates.get(kind) or 0) for kind in _rank_order(rank)),
                    row.per_serving, row.sku)

        return min(close, key=move_key)

    # 1. One item in every requested group, in the order the shopper named them,
    #    then (round by round) a second or third distinct item up to the variety target.
    for round_no in range(variety_target):
        for group in req.groups:
            if group == "condiment" and round_no > 0:
                continue
            if sum(1 for row in chosen if row.group == group) != round_no:
                continue
            move = best_move(group, prefer_new=True)
            if move is not None and (round_no == 0 or move.sku not in by_sku):
                add(move)

    # 2. Fill each group toward its servings target, always topping up the group
    #    that is furthest behind (relative to its need).
    blocked: set[str] = set()
    for _ in range(400):
        have = _have(chosen)
        behind = [
            (have.get(group, 0.0) / need[group], group)
            for group in req.groups
            if group not in blocked and have.get(group, 0.0) + 1e-6 < need[group]
        ]
        if not behind:
            break
        behind.sort()
        group = behind[0][1]
        move = best_move(group, prefer_new=False)
        if move is None:
            blocked.add(group)
            continue
        add(move)

    # A minimum spend may only top up unmet meal needs.
    if minimum is not None:
        blocked = set()
        for _ in range(400):
            lines = _lines_of(chosen)
            if lines:
                paid = settlement_for(lines, _quote(chosen, shipping), methods, rank)["total"]
            else:
                paid = 0.0
            if paid + 1e-6 >= minimum:
                break
            have = _have(chosen)
            order = sorted(
                (group for group in req.groups if group not in blocked),
                key=lambda group: (have.get(group, 0.0) / need[group], req.groups.index(group)),
            )
            if not order:
                break
            group = order[0]
            move = best_move(group, prefer_new=True)
            if move is None:
                blocked.add(group)
                continue
            add(move)

        # Reach the spend band by changing products, preserving meal quantities.
        for _ in range(40):
            paid = settlement_for(_lines_of(chosen), _quote(chosen, shipping), methods, rank)["total"]
            if paid + 1e-6 >= minimum:
                break
            moves = []
            for index, old in enumerate(chosen):
                if old.group == "condiment":
                    continue
                for candidate in pool.get(old.group) or []:
                    if candidate.sku in by_sku:
                        continue
                    qty = max(1, math.ceil(old.servings * old.qty / candidate.servings - 1e-9))
                    supplied = candidate.servings * qty
                    if supplied > old.servings * old.qty + candidate.servings * 0.25 + 1e-6:
                        continue
                    replacement = _Row(candidate.item, candidate.group, candidate.servings, candidate.basis, qty)
                    trial = chosen[:index] + [replacement] + chosen[index + 1:]
                    quote = _quote(trial, shipping)
                    if quote["total_landed_cost"] > ceiling + 1e-6:
                        continue
                    settlement = settlement_for(_lines_of(trial), quote, methods, rank)
                    charge = settlement["total"]
                    if charge <= paid + 1e-6:
                        continue
                    key = (charge >= minimum, -abs(charge - minimum),
                           tuple(benefit_value(settlement, kind) for kind in _rank_order(rank)))
                    moves.append((key, trial))
            if not moves:
                break
            chosen = max(moves, key=lambda move: move[0])[1]
            by_sku = {row.sku: row for row in chosen}
    return chosen


def _evaluate(
    name: str,
    rows: list[_Row],
    req: MealRequest,
    ceiling: float,
    minimum: float | None,
    shipping: tuple[float, float],
    methods: list[dict],
    rank: list[str],
) -> _Plan:
    quote = _quote(rows, shipping)
    lines = _lines_of(rows)
    settlement = settlement_for(lines, quote, methods, rank) if lines else {"total": 0.0, "benefits": [], "merchants": [], "discount": 0.0}
    need = _needs(req)
    have = _have(rows)
    coverage = {group: round(min(1.0, have.get(group, 0.0) / need[group]), 3) for group in req.groups}
    covered = sum(1 for group in req.groups if have.get(group, 0.0) > 0)
    nutrition = sum(coverage.values()) / max(1, len(coverage))
    landed = quote["total_landed_cost"]
    paid = float(settlement.get("total") or 0)
    meets = bool(rows) and landed <= ceiling + 1e-6 and (minimum is None or paid + 1e-6 >= minimum)
    order = _rank_order(rank)
    key = tuple(benefit_value(settlement, kind) for kind in order)
    merchants = sorted({str(row.item.get("merchant")) for row in rows})
    return _Plan(
        name=name,
        merchants=merchants,
        rows=rows,
        settlement=settlement,
        quote=quote,
        coverage=coverage,
        meets_band=meets,
        covered_groups=covered,
        nutrition=round(nutrition, 3),
        benefit_key=key,
    )


def _anchor_seed(rows: list[_Row], threshold: float) -> list[_Row]:
    """Best-value units from a one-shop basket, just enough to pass the shop's offer threshold."""
    seed: list[_Row] = []
    goods = 0.0
    units = sorted(
        ((row, unit) for row in rows for unit in range(row.qty)),
        key=lambda pair: (pair[1], pair[0].per_serving, pair[0].sku),
    )
    for row, _unit in units:
        if goods >= threshold - 1e-6:
            break
        found = next((kept for kept in seed if kept.sku == row.sku), None)
        if found is None:
            seed.append(_Row(item=row.item, group=row.group, servings=row.servings, basis=row.basis, qty=1))
        else:
            found.qty += 1
        goods += row.price
    return seed if goods >= threshold - 1e-6 else []


def _plan_sort_key(plan: _Plan, req: MealRequest, top_nutrition: float | None = None) -> tuple:
    asked = req.asked_groups or req.groups
    asked_covered = sum(1 for group in asked if plan.coverage.get(group, 0) > 0)
    # Nutrition is bucketed to 10% steps (within 5% of full counts as full) so payment
    # benefits decide between baskets that feed the family about equally well. A basket
    # within NUTRITION_TOLERANCE of the best one on the table counts as equal too.
    bucket = min(1.0, math.floor((plan.nutrition + 0.05) * 10 + 1e-9) / 10)
    if top_nutrition is not None and plan.nutrition + NUTRITION_TOLERANCE + 1e-9 >= top_nutrition:
        bucket = 2.0
    return (
        asked_covered,
        plan.covered_groups,
        bucket,
        plan.meets_band,
        _variety_score(plan, req),
        -(float(plan.settlement.get("total") or 0) - sum(
            float(benefit.get("amount") or 0) for benefit in plan.settlement.get("benefits", [])
            if benefit.get("kind") == "cash")),
        plan.benefit_key,
        -len(plan.merchants),
        plan.nutrition,
    )


def _variety_score(plan: _Plan, req: MealRequest) -> int:
    """Count distinct meal products; repeated units and condiments add no variety."""
    return len({row.sku for row in plan.rows if row.group != "condiment"})


def _limits(req: MealRequest, caps: dict | None) -> tuple[float, float | None, list[str]]:
    caps = caps or {}
    notes = []
    per_order = float(caps.get("per_order_cap") or caps.get("per_transaction_cap") or PER_TRANSACTION_CAP)
    monthly_cap = caps.get("monthly_cap")
    spent = float(caps.get("monthly_spent") or 0)
    ceiling = req.max_total if req.max_total is not None else per_order
    if ceiling > per_order:
        if req.min_total is not None and req.min_total > per_order:
            notes.append(
                f"Your minimum HK${req.min_total:.2f} is above the HK${per_order:.0f} per-order cap, "
                "so this basket will need an approval before payment."
            )
        else:
            notes.append(
                f"You allowed up to HK${ceiling:.2f}, but orders over HK${per_order:.0f} need an approval, "
                f"so I kept the basket at or under HK${per_order:.0f}."
            )
            ceiling = per_order
    if monthly_cap is not None:
        remaining = float(monthly_cap) - spent
        if remaining < ceiling:
            notes.append(f"Only HK${remaining:.2f} is left of your HK${float(monthly_cap):.0f} monthly cap.")
            ceiling = max(0.0, remaining)
    minimum = req.min_total
    return _money(ceiling), minimum, notes


def plan_meal(
    intent: str,
    catalog: list[dict],
    *,
    methods: list[dict] | None = None,
    benefit_rank: list[str] | None = None,
    caps: dict | None = None,
    shipping: tuple[float, float] = (400.0, 30.0),
    overrides: dict | None = None,
) -> dict:
    """Return a decision dict (needs pinned to SKUs, with reasons) for agent_graph._reason."""
    req = parse_request(intent)
    for key, value in (overrides or {}).items():
        setattr(req, key, value)
    if req.min_pct is not None and req.max_total is not None and "min_total" not in (overrides or {}):
        req.min_total = round(req.max_total * req.min_pct, 2)
    pool_methods = connected_methods(methods)
    rank = list(benefit_rank or DEFAULT_RANK)
    if req.wants_cash:
        rank = ["cash", *[kind for kind in rank if kind != "cash"]]
    ceiling, minimum, limit_notes = _limits(req, caps)
    if minimum is None and req.min_pct is not None:
        minimum = _money(ceiling * req.min_pct)
    if minimum is not None and minimum > ceiling + 1e-6:
        return _ask(
            f"You asked to spend at least HK${minimum:.2f}, but the most this order can be is HK${ceiling:.2f}. "
            "Should I lower the minimum, or raise the cap?",
            req,
        )
    if not pool_methods:
        return _ask("No payment method is connected on your profile. Connect one, then ask again.", req)

    catalog = [item for item in catalog if choose_line_tender(
        str(item.get("merchant") or ""), 0, pool_methods, rank).get("route")]
    strategies: list[tuple[str, set[str] | None]] = [(f"{merchant} only", {merchant}) for merchant in WHITELIST]
    strategies.append(("mixed shops", None))
    if req.merchants:
        strategies = [("requested shops", set(req.merchants))]
    plans: list[_Plan] = []
    for name, merchants in strategies:
        pool = _pool(catalog, merchants, ceiling, req.groups)
        if not any(pool.values()):
            continue
        rows = _fill(pool, req, ceiling, minimum, shipping, pool_methods, rank)
        if not rows:
            continue
        plans.append(_evaluate(name, rows, req, ceiling, minimum, shipping, pool_methods, rank))
    # Anchor baskets: unlock one shop's offer, then top up from every shop.
    mixed_pool = _pool(catalog, None, ceiling, req.groups)
    for merchant, threshold in (OFFER_THRESHOLDS.items() if not req.merchants else []):
        alone = next((plan for plan in plans if plan.name == f"{merchant} only"), None)
        if alone is None or threshold >= ceiling:
            continue
        seed = _anchor_seed(alone.rows, threshold)
        if not seed:
            continue
        rows = _fill(mixed_pool, req, ceiling, minimum, shipping, pool_methods, rank, seed=seed)
        if len({str(row.item.get("merchant")) for row in rows}) < 2:
            continue
        plans.append(
            _evaluate(f"{merchant} offer + top-up", rows, req, ceiling, minimum, shipping, pool_methods, rank)
        )
    if not plans:
        return _ask("The shelf has no priced food in these groups that fits this budget.", req)
    from basket_optimizer import optimize_basket

    optimization_runs = []
    allocation_catalog = [item for item in catalog if not req.merchants or item.get("merchant") in req.merchants]
    for candidate in list(plans):
        result = optimize_basket(_lines_of(candidate.rows), allocation_catalog,
                                 methods=pool_methods, rank=rank, max_total=ceiling,
                                 min_total=minimum, shipping=shipping)
        optimization_runs.append(result["optimization"])
        if result["optimization"].get("feasible") and any(
            line["sku"] != old.sku for line, old in zip(result["lines"], candidate.rows)
        ):
            by_id = {item["id"]: item for item in allocation_catalog}
            rows = [_Row(by_id[line["sku"]], old.group, old.servings, old.basis, old.qty)
                    for old, line in zip(candidate.rows, result["lines"])]
            plans.append(_evaluate(f"{candidate.name} optimized allocation", rows, req, ceiling,
                                   minimum, shipping, pool_methods, rank))
    eligible = plans
    top_nutrition = max(plan.nutrition for plan in eligible)
    plans.sort(key=lambda plan: _plan_sort_key(plan, req, top_nutrition), reverse=True)
    best = plans[0]

    warnings = []
    if minimum is not None and float(best.settlement.get("total") or 0) < minimum - 1e-6:
        warnings.append(
            f"Realistic meal quantities charge HK${float(best.settlement.get('total') or 0):.2f}, "
            f"below your HK${minimum:.2f} minimum. I stopped at household serving targets "
            "instead of adding excess food to fill the budget."
        )
    if any(value < 0.95 for group, value in best.coverage.items() if group != "condiment"):
        warnings.append("This budget and catalog cannot cover all realistic meal amounts; review the serving shortfalls before confirming.")
    limit_notes.extend(warnings)

    context = {
        "request": req,
        "ceiling": ceiling,
        "minimum": minimum,
        "methods": pool_methods,
        "rank": rank,
        "shipping": shipping,
    }
    reasons = line_reasons(best.rows, context, best.settlement)
    needs = []
    for index, row in enumerate(best.rows):
        needs.append(
            {
                "query": row.item["name"],
                "sku": row.sku,
                "qty": row.qty,
                "sell_point": "",
                "priority": index + 1,
                "reason": reasons[row.sku],
                "group": row.group,
            }
        )
    rationale = order_rationale(best, plans, context, limit_notes)
    steps = optimiser_steps(req, ceiling, minimum, plans, best, context)
    effective_cost = _money(float(best.settlement.get("total") or 0) - sum(
        float(benefit.get("amount") or 0) for benefit in best.settlement.get("benefits", [])
        if benefit.get("kind") == "cash"))
    allocation_summary = {
        "tool": "optimize_basket", "search": "bounded_beam", "global_optimum_guaranteed": False,
        "evaluations": sum(run["evaluations"] for run in optimization_runs),
        "candidate_baskets": len(plans), "selected_effective_cost": effective_cost,
        "merchant_count": len(best.merchants),
    }
    steps.append({"thought": "Compare merchant allocations for the planned quantities.",
                  "action": "optimize_basket", "source": "optimizer",
                  "observation": f"Evaluated {allocation_summary['evaluations']} allocations across {len(plans)} baskets; "
                                 f"selected {len(best.merchants)} merchants, charge HK${best.settlement['total']:.2f}, "
                                 f"effective cost after cash cashback HK${effective_cost:.2f}. Search is bounded."})
    return {
        "needs": needs,
        "query": ", ".join(need["query"] for need in needs),
        "qty": len(needs),
        "sell_point": "",
        "thought": rationale["headline"],
        "reply": rationale["text"],
        "model": "meal",
        "meal": {
            "request": req.as_dict(),
            "ceiling": ceiling,
            "minimum": minimum,
            "strategy": best.name,
            "optimization": allocation_summary,
            "coverage": best.coverage,
            "payment": rationale["payment"],
            "benefits": best.settlement.get("benefits") or [],
            "discount": best.settlement.get("discount") or 0,
            "meets_band": best.meets_band,
            "minimum_shortfall": _money(max(0.0, (minimum or 0) - float(best.settlement.get("total") or 0))),
            "planned_total": best.settlement.get("total"),
            "planned_landed": best.quote["total_landed_cost"],
            "alternatives": [
                {
                    "strategy": plan.name,
                    "landed": plan.quote["total_landed_cost"],
                    "charge": plan.settlement.get("total"),
                    "covered_groups": plan.covered_groups,
                    "nutrition": plan.nutrition,
                    "meets_band": plan.meets_band,
                    "benefits": {kind: benefit_value(plan.settlement, kind) for kind in BENEFIT_KINDS},
                }
                for plan in plans
            ],
            "notes": limit_notes,
            "warnings": warnings,
            "serving_targets": _needs(req),
            "servings_supplied": _have(best.rows),
        },
        "react_steps": steps,
    }


def _ask(question: str, req: MealRequest) -> dict:
    return {
        "question": question,
        "thought": question,
        "reply": question,
        "model": "meal",
        "meal": {"request": req.as_dict()},
    }


# --------------------------------------------------------------------------
# Reasons
# --------------------------------------------------------------------------


def _benefit_text(benefits: list[dict]) -> str:
    parts = []
    for benefit in benefits:
        kind = benefit.get("kind")
        amount = float(benefit.get("amount") or 0)
        if not amount:
            continue
        if kind == "cash":
            parts.append(f"HK${amount:.2f} cashback")
        else:
            parts.append(f"{amount:g} {BENEFIT_LABELS.get(kind, kind)}")
    return " and ".join(parts)


def _tender_for(settlement: dict, merchant: str) -> dict:
    for group in settlement.get("merchants") or []:
        if group.get("merchant") == merchant:
            return group
    return {}


def line_reasons(rows: list[_Row], context: dict, settlement: dict) -> dict[str, str]:
    req: MealRequest = context["request"]
    ceiling = float(context["ceiling"])
    methods = context["methods"]
    rank = context["rank"]
    need = _needs(req)
    have = _have(rows)
    per_group: dict[str, list[_Row]] = {}
    for row in rows:
        per_group.setdefault(row.group, []).append(row)
    reasons = {}
    for row in rows:
        label, per_day, _serving = GROUPS[row.group]
        line_total = _money(row.price * row.qty)
        line_servings = row.servings * row.qty
        group_need = need.get(row.group, per_day * req.person_days)
        share = line_servings / group_need if group_need else 0
        group_share = have.get(row.group, 0.0) / group_need if group_need else 0
        mates = [other for other in per_group.get(row.group, []) if other.sku != row.sku]
        merchant = str(row.item.get("merchant") or "")
        merchant_settlement = _tender_for(settlement, merchant)
        group_tender = merchant_settlement.get("payment") or {}
        subtotal = float(merchant_settlement.get("subtotal") or line_total)
        tender = choose_line_tender(merchant, subtotal, methods, rank)
        line_benefits = [
            {**benefit, "amount": _money(float(benefit.get("amount") or 0) * line_total / subtotal)}
            for benefit in merchant_settlement.get("benefits", tender.get("benefits") or [])
        ]
        parts = [
            f"[{label.split(' (')[0].capitalize()}] {row.item.get('name')} from {merchant}: "
            f"HK${row.price:.2f} x {row.qty} = HK${line_total:.2f}."
            + (f" Category {row.item['category']}." if row.item.get("category") else ""),
            f"Why this item: about {row.servings:g} servings per pack ({row.basis}), "
            f"so HK${row.per_serving:.2f} per serving"
            + (
                f"; picked {('because you asked for ' + label) if row.group in req.asked_groups else 'to add variety beyond the groups you named'}."
            ),
            f"Quantity: {row.qty} selling units x {row.servings:g} "
            + ("noodle packs" if row.group == "staple" and "packs of noodles" in row.basis else "servings per selling unit")
            + f" = {line_servings:g} "
            + ("packs (1 serving each). " if row.group == "staple" and "packs of noodles" in row.basis else "servings. ")
            + 
            f"A family of {req.family} for {req.days} days needs about {group_need:g} {label.split(' (')[0]} servings "
            f"({per_day:g} per person per day), so this line covers {share * 100:.0f}%"
            + (
                f" and the {len(mates) + 1} {label.split(' (')[0]} items together cover {min(group_share, 9.99) * 100:.0f}%"
                if mates
                else ""
            )
            + (
                " (pack rounding leaves some servings for later)."
                if group_share > 1.05 and context.get("minimum") is not None
                else "."
            ),
            f"Budget: HK${line_total:.2f} is {line_total / ceiling * 100:.1f}% of the HK${ceiling:.0f} cap.",
        ]
        bonus = _benefit_text(line_benefits)
        payer = group_tender.get("label") or tender.get("label")
        if bonus:
            parts.append(f"Payment: paid with {payer} at {merchant}, this line earns about {bonus}.")
        elif payer:
            parts.append(f"Payment: paid with {payer} at {merchant}.")
        if row.group == "condiment":
            parts[1] = "Why this item: a supporting soup base or seasoning, not staple or protein meal coverage."
            parts[2] = (
                f"Quantity: {row.qty} selling unit(s) for {req.family} people across {req.days} days; "
                f"capped at {max(1, math.ceil(req.person_days / 30))} household supplies."
            )
        reasons[row.sku] = "\n".join(parts)
    return reasons


def choose_line_tender(merchant: str, amount: float, methods: list[dict], rank: list[str]) -> dict:
    from benefits import choose_tender

    return choose_tender(merchant, amount, methods, rank)


def _tender_table(merchant: str, amount: float, methods: list[dict]) -> list[dict]:
    rows = []
    for method in methods:
        if method.get("merchants") and merchant not in method["merchants"]:
            continue
        quote = quote_tender(merchant, amount, method)
        rows.append(quote)
    return rows


def order_rationale(best: _Plan, plans: list[_Plan], context: dict, notes: list[str]) -> dict:
    req: MealRequest = context["request"]
    ceiling = context["ceiling"]
    minimum = context["minimum"]
    methods = context["methods"]
    rank = _rank_order(context["rank"])
    settlement = best.settlement
    charge = float(settlement.get("total") or 0)
    landed = best.quote["total_landed_cost"]
    groups = ", ".join(GROUPS[group][0] for group in req.groups)
    read = [
        f"I read: cap HK${ceiling:.2f}"
        + (f" (from {req.max_source})" if req.max_source else " (your per-order limit)"),
        (
            f"minimum spend HK${minimum:.2f}"
            + (f" ({req.min_pct * 100:g}% of the cap, from {req.min_source})" if req.min_pct else f" (from {req.min_source})")
        )
        if minimum is not None
        else "no minimum spend",
        f"{req.days} days" + ("" if req.days_source != "default" else " (default)"),
        f"family of {req.family}" + ("" if req.family_source != "default" else " (no size given, assumed 1)"),
    ]
    head = "; ".join(read) + "."
    group_text = f"Food groups: {groups}."
    if req.variety and req.asked_groups:
        group_text += " You asked for more categories, so I added the extra groups and at least two items in each where the budget allows."
    coverage = ", ".join(
        f"{GROUPS[group][0].split(' (')[0]} {min(value, 1.0) * 100:.0f}%" for group, value in best.coverage.items()
    )
    compare = []
    for plan in plans[:5]:
        mark = "chosen" if plan is best else ("fits" if plan.meets_band else "misses the spend band")
        bonus = ", ".join(
            f"{BENEFIT_LABELS[kind]} {benefit_value(plan.settlement, kind):g}" for kind in rank if benefit_value(plan.settlement, kind)
        ) or "no benefits"
        compare.append(
            f"{plan.name}: charge HK${float(plan.settlement.get('total') or 0):.2f}, "
            f"{plan.covered_groups}/{len(req.groups)} groups, {plan.nutrition * 100:.0f}% of servings, {bonus} ({mark})"
        )
    payment_lines = []
    payment_summary = []
    for group in settlement.get("merchants") or []:
        merchant = group.get("merchant")
        subtotal = float(group.get("subtotal") or 0)
        table = _tender_table(merchant, subtotal, methods)
        options = "; ".join(
            f"{row['label']}: " + (_benefit_text(row["benefits"]) or "no benefit")
            + (f", HK${row['discount']:.2f} shop discount" if row.get("discount") else "")
            for row in table
        )
        chosen = group.get("payment") or {}
        payment_lines.append(
            f"For {merchant} (goods HK${subtotal:.2f}) your connected methods compare as: {options}. "
            f"I picked {chosen.get('label')} because your benefit ranking puts {BENEFIT_LABELS[rank[0]]} first"
            + (f", then {BENEFIT_LABELS[rank[1]]}" if len(rank) > 1 else "")
            + f". {group.get('because') or ''}".rstrip()
        )
        payment_summary.append(
            {
                "merchant": merchant,
                "route": chosen.get("route"),
                "label": chosen.get("label"),
                "last4": chosen.get("last4"),
                "amount": chosen.get("amount"),
                "benefits": group.get("benefits") or [],
                "options": [
                    {
                        "route": row["route"],
                        "label": row["label"],
                        "benefits": row["benefits"],
                        "discount": row["discount"],
                    }
                    for row in table
                ],
            }
        )
    earned = _benefit_text(settlement.get("benefits") or []) or "no card benefits"
    discount = float(settlement.get("discount") or 0)
    totals = (
        f"Planned landed total HK${landed:.2f}"
        + (f", minus HK${discount:.2f} shop discount" if discount else "")
        + f", so the card is charged HK${charge:.2f}"
        + (f" (inside your HK${minimum:.2f}-HK${ceiling:.2f} band)." if minimum is not None and charge >= minimum else f" (under HK${ceiling:.2f}).")
        + f" Benefits this order: {earned}."
    )
    text = " ".join(
        [
            f"Food for {req.days} days, {len(best.rows)} different products.",
            head,
            group_text,
            f"I compared {len(plans)} ways to build the basket: " + " | ".join(compare) + ".",
            f"Chosen: {best.name}, {len(best.rows)} products. Servings covered: {coverage}.",
            *payment_lines,
            totals,
            *notes,
        ]
    )
    headline = (
        f"Optimiser built {len(best.rows)} products for {req.family} people x {req.days} days "
        f"from {best.name}, charge HK${charge:.2f}, {earned}."
    )
    return {"text": text, "headline": headline, "payment": payment_summary}


def optimiser_steps(req: MealRequest, ceiling: float, minimum: float | None, plans: list[_Plan], best: _Plan, context: dict) -> list[dict]:
    rank = _rank_order(context["rank"])
    methods = context["methods"]
    need = _needs(req)
    steps = [
        {
            "thought": "Read the budget, minimum spend, days, family size and food groups from the sentence.",
            "action": "parse_request",
            "observation": (
                f"cap HK${ceiling:.2f}; minimum "
                + (f"HK${minimum:.2f}" if minimum is not None else "none")
                + f"; {req.days} days; family {req.family}; groups {', '.join(req.groups)}."
            ),
            "source": "optimizer",
        },
        {
            "thought": "Turn days x people into servings per food group.",
            "action": "servings_target",
            "observation": "; ".join(f"{group} {value:g} servings" for group, value in need.items()) + ".",
            "source": "optimizer",
        },
        {
            "thought": "Read the connected payment methods and the benefit ranking from the profile.",
            "action": "read_profile",
            "observation": (
                "methods: " + ", ".join(str(m.get("label") or m.get("route")) for m in methods)
                + "; ranking: " + " > ".join(BENEFIT_LABELS[kind] for kind in rank) + "."
            ),
            "source": "optimizer",
        },
        {
            "thought": "Fill a basket per shop strategy, best servings per dollar first, then score by spend band, coverage and ranked benefits.",
            "action": "compare_strategies",
            "observation": " | ".join(
                f"{plan.name}: HK${float(plan.settlement.get('total') or 0):.2f}, {plan.covered_groups} groups, "
                f"{plan.nutrition * 100:.0f}% servings, "
                + ", ".join(f"{BENEFIT_LABELS[k]} {v:g}" for k, v in zip(rank, plan.benefit_key) if v)
                for plan in plans
            ),
            "source": "optimizer",
        },
        {
            "thought": "Keep the winner. Policy still judges every line and the total next.",
            "action": "choose_basket",
            "observation": f"{best.name}, {len(best.rows)} products, landed HK${best.quote['total_landed_cost']:.2f}.",
            "source": "optimizer",
        },
    ]
    return steps


# --------------------------------------------------------------------------
# After the shopper edits the basket
# --------------------------------------------------------------------------


def is_meal_intent(intent: str) -> bool:
    text = intent.casefold()
    food = any(word in text for word in ("food", "meal", "ingredient", "grocer"))
    has_days = re.search(r"\d+\s*days?|week", text) is not None
    has_money = re.search(r"budget|hkd|hk\$|\$\s*\d|maximum|\bmax\b|\bcap\b", text) is not None
    return food and (has_days or has_money)


def describe_lines(
    intent: str,
    lines: list[dict],
    catalog_by_sku: dict[str, dict],
    *,
    methods: list[dict] | None,
    benefit_rank: list[str] | None,
    caps: dict | None,
    quote: dict,
    settlement: dict,
) -> dict:
    """Reasons and band checks for a basket the shopper edited."""
    req = parse_request(intent)
    ceiling, minimum, _notes = _limits(req, caps)
    if minimum is None and req.min_pct is not None:
        minimum = _money(ceiling * req.min_pct)
    rows = []
    for line in lines:
        item = catalog_by_sku.get(str(line.get("sku"))) or {}
        group = classify(item) if item else None
        if group is None:
            continue
        if group not in req.groups:
            req.groups.append(group)
        count, basis = servings(item, group)
        rows.append(_Row(item=item, group=group, servings=count, basis=basis, qty=int(line.get("qty") or 1)))
    context = {
        "request": req,
        "ceiling": ceiling,
        "minimum": minimum,
        "methods": connected_methods(methods),
        "rank": list(benefit_rank or DEFAULT_RANK),
    }
    reasons = line_reasons(rows, context, settlement) if rows else {}
    landed = float(quote.get("total_landed_cost") or 0)
    charge = float(settlement.get("total") or 0)
    warnings = []
    # Only the shopper's own stated maximum blocks here. Policy caps are the
    # policy engine's job (it may ESCALATE instead of refusing).
    over = req.max_total is not None and landed > req.max_total + 1e-6
    if over:
        warnings.append(f"The edited basket lands at HK${landed:.2f}, over your HK${req.max_total:.2f} maximum.")
    elif landed > ceiling + 1e-6:
        warnings.append(f"The edited basket lands at HK${landed:.2f}, above the HK${ceiling:.2f} the plan aimed for; the policy check decides if it can go ahead.")
    under_min = None
    if minimum is not None and charge + 1e-6 < minimum:
        short = _money(minimum - charge)
        basis = (
            f"{req.min_pct * 100:g}% of your HK${req.max_total:.2f} cap"
            if req.min_pct is not None and req.max_total is not None
            else "the minimum you asked for"
        )
        under_min = {"charge": _money(charge), "minimum": _money(minimum), "short_by": short, "basis": basis}
        # A warning, not a block: the shopper may choose a smaller basket.
        warnings.append(
            f"Under your minimum: the edited basket charges HK${charge:.2f}, HK${short:.2f} below the "
            f"HK${minimum:.2f} minimum ({basis}). You can still confirm it."
        )
    need = _needs(req)
    have = _have(rows)
    coverage = {group: round(min(1.0, have.get(group, 0.0) / need[group]), 3) for group in req.groups if need.get(group)}
    return {
        "reasons": reasons,
        "warnings": warnings,
        "over_max": over,
        "under_min": under_min,
        "coverage": coverage,
        "ceiling": ceiling,
        "minimum": minimum,
    }


def alternatives(
    intent: str,
    sku: str,
    catalog: list[dict],
    *,
    exclude: set[str] | None = None,
    limit: int = 6,
) -> list[dict]:
    """Swap options for one basket line: same food group, best servings per dollar first."""
    by_sku = {str(item.get("id")): item for item in catalog}
    current = by_sku.get(sku)
    if current is None:
        return []
    group = classify(current)
    if group is None:
        category = current.get("category")
        pool = [item for item in catalog if item.get("category") == category]
        group_label = str(category)
    else:
        pool = [item for item in catalog if classify(item) == group]
        group_label = GROUPS[group][0]
    blocked = set(exclude or set()) | {sku}
    cur_count, _basis = servings(current, group) if group else (1.0, "")
    cur_per = float(current.get("price") or 0) / max(cur_count, 0.1)
    rows = []
    for item in pool:
        item_sku = str(item.get("id") or "")
        if item_sku in blocked or item.get("in_stock") is False:
            continue
        if str(item.get("merchant") or "") not in WHITELIST:
            continue
        price = float(item.get("price") or 0)
        if price <= 0:
            continue
        count, basis = servings(item, group) if group else (1.0, "")
        per = price / max(count, 0.1)
        same_shop = item.get("merchant") == current.get("merchant")
        rows.append((not same_shop, per, price, item_sku, item, count, basis))
    rows.sort(key=lambda row: row[:4])
    out = []
    for _other, per, price, item_sku, item, count, basis in rows[:limit]:
        diff = per - cur_per
        if abs(diff) < 0.005:
            compare = "same price per serving"
        elif diff < 0:
            compare = f"HK${-diff:.2f} cheaper per serving"
        else:
            compare = f"HK${diff:.2f} more per serving"
        out.append(
            {
                "sku": item_sku,
                "name": item.get("name"),
                "merchant": item.get("merchant"),
                "category": item.get("category"),
                "price": _money(price),
                "image_url": item.get("image_url") or "",
                "servings": count,
                "per_serving": _money(per),
                "reason": (
                    f"Same group ({group_label}). About {count:g} servings ({basis}), HK${per:.2f} per serving, "
                    f"{compare} than the current pick"
                    + ("" if item.get("merchant") == current.get("merchant") else f"; sold by {item.get('merchant')}, which may change the card and benefits")
                    + "."
                ),
            }
        )
    return out
