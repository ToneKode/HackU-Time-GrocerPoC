"""Live LangGraph for POST /agent/intent.

Same spine as graph/shopping_graph.py: reason, a fixed plan, tool calls,
then a policy branch. Each step is hashed into audit_log before the next
edge runs. Tool calls hit the mall and the policy service.
"""

from __future__ import annotations

import hashlib
import json
import math
import operator
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from benefits import DEFAULT_RANK, connected_methods, explain_pick, settlement_for
from basket import (
    _blacklist_reply,
    _is_meal_plan,
    assign_same_merchant,
    fit_basket,
    named_merchant,
    needs_for_every_category,
    needs_from,
    options_for,
    plan_fuzzy,
    wants_same_merchant,
)
from clients import PaymentClient, PolicyClient, engine_thought, policy_snapshot, public_escalation
from fake_mall import FileMall
from meal_plan import alternatives as meal_alternatives
from meal_plan import describe_lines, is_meal_intent, plan_meal
from models import ActionPlan
from draft_store import DraftStore
from pathlib import Path
from openrouter import OpenRouterPlanner, normalize_react
from pick import goal_from, planner_shelf, resolve_pick

GENESIS = "0" * 64

THOUGHTS = {
    "INTENT_RECEIVED": "Read the sentence. Set query and qty.",
    "PLAN": "The tool order is fixed.",
    "SEARCH": "Search the sandbox and keep the first product.",
    "CART_PRICED": "Price the cart. Shipping can change the amount.",
    "POLICY_CHECK": "Ask the policy engine. This node does not decide.",
    "PAYMENT": "Charge the landed total.",
    "ESCALATION_CREATED": "Open the 10-minute approval and return now.",
    "FOLLOW_UP": "The shopper has to choose before anyone pays.",
    "HALTED": "Policy said HALT. Do not pay.",
    "ESCALATION_REFUSED": "Mother refused. Do not pay.",
    "ESCALATION_EXPIRED": "The 10 minutes ran out. Do not pay.",
    "PREVIEW_READY": "Quote is ready. The shopper asked not to check out.",
}

_PREVIEW_ONLY = re.compile(
    r"\b(?:don't|do not|never)\s+(?:buy|purchase|order)|"
    r"\bwithout\s+(?:buying|purchasing|ordering)|"
    r"\b(?:quote|compare)\s+only\b|"
    r"\bno\s+purchase\b|"
    r"\bshow\s+me\b.{0,100}\bbefore\s+(?:checkout|ordering|buying)\b",
    re.IGNORECASE,
)
_MAX_TOTAL = re.compile(
    r"(?:do not spend more than|don't spend more than|no more than|not more than|"
    r"maximum(?: delivered total)?(?: is| of)?|max(?:imum)?(?: spend)?(?: is| of)?|"
    r"under|within|at most|up to|budget(?: is| of)?|limit(?: is| of)?)\s*"
    r"(?:HK\$|HKD|\$)?\s*(\d+(?:\.\d{1,2})?)\b",
    re.IGNORECASE,
)


class AgentState(TypedDict, total=False):
    intent: str
    monthly_spent: float
    account_id: str
    escalation_id: str
    escalation_status: str
    policy_status: str
    goal: dict
    product: dict
    quote: dict
    policy: dict
    escalation: dict
    payment: dict
    needs: list
    lines: list
    repairs: list
    question: str
    reply: str
    payment_route: str
    payment_reason: str
    order_id: str
    profile: dict
    policy_caps: dict
    policy_events: list
    basket_policy: dict
    llm_react: list
    decision_events: list
    model_tools_used: bool
    meal: dict
    run_id: str
    plan_status: str
    stop: bool
    preview_only: bool
    user_max_total: float
    payment_draft: dict
    settlement: dict
    pending_event: dict
    path: Annotated[list, operator.add]
    audit_log: Annotated[list, operator.add]


def parse_goal(intent: str) -> dict:
    text = intent.casefold()
    qty = 1
    match = re.search(r"\b(\d+)\b", text)
    if match:
        qty = max(1, int(match.group(1)))
    if "bulk" in text:
        query = "bulk"
    elif "toilet" in text:
        query = "toilet"
    else:
        skip = {"buy", "please", "a", "the", "some"}
        query = " ".join(word for word in text.split() if word not in skip) or intent
    return {"intent": intent, "query": query, "qty": qty}


def _pending(
    event: str,
    status: str,
    reason: str,
    thought: str | None = None,
    result: dict | None = None,
) -> dict:
    pending = {
        "event": event,
        "status": status,
        "reason": reason,
        "thought": thought or THOUGHTS[event],
    }
    if result is not None:
        pending["result"] = result
    return pending


def _stamp(log: list[dict], pending: dict) -> dict:
    index = len(log)
    prev = log[-1]["hash"] if log else GENESIS
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    material = "|".join([str(index), ts, pending["event"], pending["status"], pending["reason"], prev])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return {
        "index": index,
        "ts": ts,
        "event": pending["event"],
        "status": pending["status"],
        "reason": pending["reason"],
        "thought": pending["thought"],
        "result": pending.get("result"),
        "prev_hash": prev,
        "hash": digest,
    }


def _join_reply(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _blacklist_only_reply(state: AgentState) -> str:
    product = state.get("product") or {}
    return _blacklist_reply(
        [
            {
                "category": product.get("category") or "That category",
                "merchant": product.get("merchant") or "",
                "sku": product.get("id") or "",
                "name": product.get("name") or "",
                "_rule": "category_blacklisted",
            }
        ],
        False,
    )


def _product(raw: dict) -> dict:
    return {
        "id": raw["id"],
        "name": raw["name"],
        "price": round(float(raw["price"]), 2),
        "currency": raw.get("currency", "HKD"),
        "merchant": raw["merchant"],
        "category": raw["category"],
        # Most rows in hk_products_full.json carry "stock": null.
        "stock": int(raw.get("stock") or 0),
        "image_url": raw.get("image_url") or "",
        "sell_point": raw.get("sell_point") or "",
    }


def _quote(raw: dict) -> dict:
    lines = []
    for item in raw["line_items"]:
        lines.append(
            {
                "sku": item["sku"],
                "name": item["name"],
                "merchant": item["merchant"],
                "category": item["category"],
                "unit_price": round(float(item["unit_price"]), 2),
                "qty": int(item["qty"]),
                "line_total": round(float(item["line_total"]), 2),
            }
        )
    return {
        "line_items": lines,
        "subtotal": round(float(raw["subtotal"]), 2),
        "shipping_fee": round(float(raw["shipping_fee"]), 2),
        "tax": round(float(raw.get("tax", 0)), 2),
        "total_landed_cost": round(float(raw["total_landed_cost"]), 2),
        "currency": raw.get("currency", "HKD"),
        "free_shipping_threshold": round(float(raw.get("free_shipping_threshold", 400)), 2),
    }


def build_react(audit_log: list[dict], goal: dict | None, llm_react: list | None) -> list[dict]:
    """Thought, action, observation. Reasoning steps come first, then each tool.

    Each reasoning step keeps its own source: "llm" when a model wrote it,
    "optimizer" when the deterministic meal planner computed it.
    """
    steps = []
    for item in llm_react or []:
        if isinstance(item, dict) and (item.get("thought") or item.get("observation")):
            source = str(item.get("source") or "llm")
            steps.append(
                {
                    "thought": str(item.get("thought") or ""),
                    "action": str(item.get("action") or "reason"),
                    "observation": str(item.get("observation") or ""),
                    "source": source if source in {"llm", "optimizer", "catalog", "scripted", "agent"} else "llm",
                }
            )
    model = str((goal or {}).get("model") or "")
    for entry in audit_log:
        observation = str(entry.get("reason") or "")
        result = entry.get("result") if isinstance(entry.get("result"), dict) else None
        if result:
            amount = result.get("amount")
            amount_text = f"HK${float(amount):.2f}" if isinstance(amount, (int, float)) else ""
            observation = " | ".join(
                part
                for part in (
                    observation,
                    str(result.get("status") or ""),
                    str(result.get("rule") or ""),
                    amount_text,
                )
                if part
            )
        if entry.get("event") == "INTENT_RECEIVED" and model == "catalog":
            source = "catalog"
        elif entry.get("event") == "INTENT_RECEIVED" and model == "scripted":
            source = "scripted"
        elif entry.get("event") == "INTENT_RECEIVED" and model.startswith("meal"):
            # The meal planner is deterministic code. It used to be labelled
            # "llm" here even though no model was called.
            source = "optimizer"
        elif entry.get("event") == "INTENT_RECEIVED" and model:
            source = "llm"
        else:
            source = "agent"
        steps.append(
            {
                "thought": str(entry.get("thought") or ""),
                "action": str(entry.get("event") or ""),
                "observation": observation,
                "source": source,
            }
        )
    return steps


def _failure(name: str, event: str, reason: str) -> dict:
    return {
        "path": [name],
        "plan_status": "FAILED",
        "stop": True,
        "pending_event": _pending(event, "FAILED", reason),
    }


def _user_max_total(intent: str) -> float | None:
    match = _MAX_TOTAL.search(intent)
    return round(float(match.group(1)), 2) if match else None


def _finite_money(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return round(amount, 2) if math.isfinite(amount) else None


def _verify_cart_quote(raw: dict, requested: list[dict], catalog: list[dict]) -> None:
    """Fail closed when the priced cart diverges from catalogue data or totals."""
    if not isinstance(raw, dict) or not isinstance(raw.get("line_items"), list):
        raise ValueError("Cart quote is missing line items")
    if raw.get("currency") != "HKD" or len(raw["line_items"]) != len(requested):
        raise ValueError("Cart quote has an unexpected currency or item count")
    products = {str(item.get("id")): item for item in catalog}
    quoted_by_key = {}
    for line in raw["line_items"]:
        if not isinstance(line, dict):
            raise ValueError("Cart quote contains an invalid line")
        key = (str(line.get("sku") or ""), line.get("qty"))
        if key in quoted_by_key:
            raise ValueError("Cart quote contains a duplicate line")
        quoted_by_key[key] = line

    line_totals = []
    for item in requested:
        sku = str(item.get("sku") or "")
        qty = item.get("qty")
        product = products.get(sku)
        line = quoted_by_key.get((sku, qty))
        if product is None or line is None:
            raise ValueError("Cart quote does not match the requested catalogue items")
        expected_unit = _finite_money(product.get("price"))
        quoted_unit = _finite_money(line.get("unit_price"))
        quoted_total = _finite_money(line.get("line_total"))
        if (
            expected_unit is None
            or quoted_unit != expected_unit
            or line.get("merchant") != product.get("merchant")
            or line.get("category") != product.get("category")
            or isinstance(qty, bool)
            or not isinstance(qty, int)
            or qty < 1
            or quoted_total != round(expected_unit * qty, 2)
        ):
            raise ValueError("Cart price or product details differ from the catalogue")
        line_totals.append(quoted_total)

    subtotal = _finite_money(raw.get("subtotal"))
    shipping = _finite_money(raw.get("shipping_fee"))
    tax = _finite_money(raw.get("tax", 0))
    landed = _finite_money(raw.get("total_landed_cost"))
    if (
        subtotal is None
        or shipping is None
        or tax is None
        or landed is None
        or subtotal != round(sum(line_totals), 2)
        or landed != round(subtotal + shipping + tax, 2)
    ):
        raise ValueError("Cart quote totals are inconsistent")


def _profile_note(profile: dict | None) -> str:
    if not profile:
        return ""
    parts = [
        f"monthly cap HK${profile.get('monthly_cap')}",
        f"limit per order HK${profile.get('per_order_cap')}",
        f"spent this month HK${profile.get('monthly_spent', 0)}",
    ]
    last = profile.get("last_purchase")
    if isinstance(last, dict) and last.get("amount") is not None:
        parts.append(f"last purchase {last.get('merchant') or ''} HK${last.get('amount')}")
    bits = []
    for item in (profile.get("recent_orders") or [])[:5]:
        if isinstance(item, dict):
            bits.append(f"{item.get('merchant') or item.get('status') or 'order'} HK${item.get('amount')}")
    if bits:
        parts.append("past orders: " + ", ".join(bits))
    return "; ".join(parts)


def _methods(state: AgentState) -> list[dict]:
    profile = state.get("profile") or {}
    return connected_methods(profile.get("payment_methods"))


def _benefit_rank(state: AgentState) -> list[str]:
    profile = state.get("profile") or {}
    rank = list(profile.get("benefit_rank") or DEFAULT_RANK)
    text = str(state.get("intent") or "").casefold()
    if "cash back" in text or "cashback" in text:
        rank = ["cash", *[kind for kind in rank if kind != "cash"]]
    return rank


def _review_lines(state: AgentState) -> list[dict]:
    lines = list(state.get("lines") or [])
    if lines:
        return lines
    product = state.get("product") or {}
    if not product.get("id"):
        return []
    goal = state.get("goal") or {}
    quote = state.get("quote") or {}
    qty = int(goal.get("qty") or 1)
    return [
        {
            "need": product.get("name") or product["id"],
            "priority": 1,
            "sku": product["id"],
            "name": product.get("name") or product["id"],
            "merchant": product.get("merchant") or "",
            "category": product.get("category") or "",
            "sell_point": product.get("sell_point") or "",
            "qty": qty,
            "unit_price": float(product.get("price") or 0),
            "line_total": float(quote.get("subtotal") or 0),
            "image_url": product.get("image_url") or "",
            "product_reason": "",
            "merchant_reason": "",
        }
    ]


def _followup(result: dict, suggestion: dict | None) -> str:
    rule = result.get("rule") or "rule"
    reason = result.get("reason") or "The basket failed the spending rules."
    if not suggestion:
        return f"checked {rule} failed. {reason} I will not bring back an item you removed. Tell me what to look for instead."
    return (
        f"checked {rule} failed. {reason} "
        f"I can switch to {suggestion['name']} from {suggestion['merchant']} "
        f"at HK${float(suggestion['price']):.2f} instead. Want that?"
    )


def _suggestion(catalog: list[dict], lines: list[dict], removed: set[str], result: dict) -> dict | None:
    blocked = {line.get("sku") for line in lines} | removed
    expensive = max(lines, key=lambda line: float(line.get("line_total") or 0))
    category = expensive.get("category")
    candidates = [
        row
        for row in catalog
        if row.get("id") not in blocked
        and row.get("category") == category
        and float(row.get("price") or 0) < float(expensive.get("unit_price") or expensive.get("line_total") or 0)
    ]
    if not candidates:
        candidates = [
            row
            for row in catalog
            if row.get("id") not in blocked and float(row.get("price") or 0) > 0
        ]
    if not candidates:
        return None
    pick = min(candidates, key=lambda row: float(row.get("price") or 0))
    return {
        "sku": pick["id"],
        "name": pick.get("name") or pick["id"],
        "merchant": pick.get("merchant") or "",
        "price": float(pick.get("price") or 0),
        "image_url": pick.get("image_url") or "",
        "replaced_sku": expensive.get("sku"),
    }


def _policy_audit(result: dict, events: list[dict]) -> list[dict]:
    rows = []
    for event in events:
        rows.append(
            _stamp(
                rows,
                {
                    "event": event.get("event") or "POLICY_CHECK",
                    "status": event.get("status") or result.get("status") or "",
                    "reason": event.get("reason") or "",
                    "thought": event.get("thought") or engine_thought(result),
                    "result": event.get("result"),
                },
            )
        )
    if not rows:
        rows.append(
            _stamp(
                [],
                {
                    "event": "POLICY_CHECK",
                    "status": result.get("status") or "",
                    "reason": result.get("reason") or "",
                    "thought": engine_thought(result),
                    "result": policy_snapshot(result) if result.get("status") else None,
                },
            )
        )
    return rows


def _plan_shell(intent: str, status: str, **fields) -> dict:
    audit = fields.pop("audit", None) or [
        _stamp(
            [],
            {
                "event": "BASKET_REVIEW",
                "status": status,
                "reason": fields.get("reply") or status,
                "thought": fields.get("reply") or "",
            },
        )
    ]
    plan = {
        "intent": intent,
        "status": status,
        "goal": None,
        "product": None,
        "quote": fields.get("quote"),
        "policy": fields.get("policy"),
        "payment": None,
        "payment_draft": fields.get("payment_draft"),
        "settlement": fields.get("settlement"),
        "suggestion": fields.get("suggestion"),
        "escalation": fields.get("escalation"),
        "lines": fields.get("lines") or [],
        "repairs": [],
        "payment_route": "",
        "payment_reason": "",
        "question": fields.get("question") or "",
        "reply": fields.get("reply") or "",
        "react": fields.get("react") or [],
        "meal": fields.get("meal"),
        "audit_log": audit,
    }
    return ActionPlan.model_validate(plan).model_dump()


def _band_steps(meal: dict | None, quote: dict, settlement: dict) -> list[dict]:
    """One reasoning step on the spend band after the shopper edits a meal basket."""
    if not meal or meal.get("minimum") is None:
        return []
    charge = float(settlement.get("total") or 0)
    under = meal.get("under_min")
    if under:
        thought = (
            f"The edited basket is under the minimum: HK${under['charge']:.2f} is HK${under['short_by']:.2f} "
            f"below the HK${under['minimum']:.2f} minimum ({under['basis']}). That is the shopper's choice, "
            "so I warn and do not block."
        )
        observation = (
            f"Under minimum by HK${under['short_by']:.2f}: charge HK${under['charge']:.2f}, "
            f"minimum HK${under['minimum']:.2f}."
        )
    else:
        thought = (
            f"The edited basket charges HK${charge:.2f}, inside the HK${float(meal['minimum']):.2f} minimum "
            f"and HK${float(meal.get('ceiling') or 0):.2f} target."
        )
        observation = f"In band: charge HK${charge:.2f}."
    return [{"thought": thought, "action": "check_spend_band", "observation": observation, "source": "optimizer"}]


def _caps_from(profile: dict | None) -> dict:
    if not profile:
        return {}
    caps = {}
    for key in ("monthly_cap", "per_order_cap", "bulk_ceiling"):
        if profile.get(key) is not None:
            caps[key] = profile[key]
    return caps


def _policy_kwargs(state: AgentState) -> dict:
    raw = state.get("policy_caps") or {}
    out = {}
    if raw.get("monthly_cap") is not None:
        out["monthly_cap"] = raw["monthly_cap"]
    if raw.get("per_order_cap") is not None:
        out["per_transaction_cap"] = raw["per_order_cap"]
    if raw.get("bulk_ceiling") is not None:
        out["bulk_ceiling"] = raw["bulk_ceiling"]
    return out


_WORKFLOW_STATUS = {
    "audit_intent": "planning",
    "audit_plan": "planning",
    "audit_search": "searching",
    "audit_cart": "quoted",
    "audit_policy": "checking",
    "audit_payment": "paying",
    "audit_escalation": "escalated",
    "audit_halt": "halted",
    "audit_abort": "aborted",
    "audit_hold": "holding",
    "audit_followup": "needs_input",
    "audit_review": "reviewing",
}


def _workflow_status(step: str, state: AgentState) -> str:
    payment = state.get("payment") or {}
    if step == "audit_payment" or step == "execute_payment":
        if payment:
            return "paid" if payment.get("success") else "failed"
    plan_status = state.get("plan_status")
    if plan_status == "HALTED":
        return "halted"
    if plan_status == "NEEDS_INPUT":
        return "needs_input"
    if plan_status == "FAILED":
        return "failed"
    if plan_status == "ESCALATED":
        return "escalated"
    if plan_status == "ABORTED":
        return "aborted"
    if plan_status == "COMPLETED":
        return "paid"
    return _WORKFLOW_STATUS.get(step, "drafting")


def _order_lines(state: AgentState) -> list[dict] | None:
    lines = state.get("lines") or []
    if lines:
        return [
            {
                "sku": line.get("sku"),
                "name": line.get("name"),
                "merchant": line.get("merchant"),
                "category": line.get("category"),
                "qty": line.get("qty"),
                "unit_price": line.get("unit_price"),
                "line_total": line.get("line_total"),
            }
            for line in lines
        ]
    product = state.get("product") or {}
    if not product:
        return None
    goal = state.get("goal") or {}
    qty = int(goal.get("qty") or 1)
    unit = float(product.get("price") or 0)
    return [
        {
            "sku": product.get("id"),
            "name": product.get("name"),
            "merchant": product.get("merchant"),
            "category": product.get("category"),
            "qty": qty,
            "unit_price": unit,
            "line_total": round(unit * qty, 2),
        }
    ]


def _order_amount(state: AgentState) -> float | None:
    payment = state.get("payment") or {}
    if payment.get("charged") is not None:
        return float(payment["charged"])
    quote = state.get("quote") or {}
    if quote.get("total_landed_cost") is not None:
        return float(quote["total_landed_cost"])
    policy = state.get("policy") or {}
    if isinstance(policy, dict) and policy.get("amount") is not None:
        return float(policy["amount"])
    return None


def _order_snapshot(state: AgentState, step: str) -> dict:
    return {
        "step": step,
        "intent": state.get("intent"),
        "plan_status": state.get("plan_status"),
        "goal": state.get("goal"),
        "product": state.get("product"),
        "quote": state.get("quote"),
        "policy": state.get("policy"),
        "lines": state.get("lines"),
        "payment": state.get("payment"),
        "question": state.get("question"),
        "reply": state.get("reply"),
        "monthly_spent": state.get("monthly_spent"),
        "policy_caps": state.get("policy_caps"),
        "escalation_id": state.get("escalation_id"),
    }


class ShoppingAgent:
    def __init__(
        self,
        mall,
        policy: PolicyClient,
        planner=None,
        spend=None,
        profile=None,
        payments: PaymentClient | None = None,
        enricher=None,
        draft_path: str | None = None,
    ):
        self.mall = mall
        self.policy = policy
        self.spend = spend
        self.profile = profile
        self.payments = payments
        self.tools = {"optimize_basket": self.optimize_basket}
        self.tool_schemas = [{"type": "function", "function": {
            "name": "optimize_basket",
            "description": "Compare merchant allocations for existing quantities using the trusted catalog and shopper benefits. Returns a bounded-search quote; does not charge or approve payment.",
            "parameters": {"type": "object", "properties": {
                "intent": {"type": "string"},
                "lines": {"type": "array", "items": {"type": "object", "properties": {
                    "sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}},
                    "required": ["sku", "qty"], "additionalProperties": False}},
            }, "required": ["intent", "lines"], "additionalProperties": False},
        }}]
        self.planner = planner or OpenRouterPlanner()
        # Optional LLM pass that explains a meal basket the optimiser built.
        # It never changes items, quantities or prices. Default: the OpenRouter
        # planner's enrich_meal_plan (skipped when no key is set). Pass
        # enricher=False to turn it off.
        if enricher is None and isinstance(self.planner, OpenRouterPlanner):
            enricher = self.planner.enrich_meal_plan
        self.enricher = enricher or None
        # payment_id -> basket that was drafted, so a capture can be saved as a paid order.
        if draft_path is None and isinstance(payments, PaymentClient):
            draft_path = os.environ.get("AGENT_DRAFT_DB") or str(Path(__file__).parent / "data" / "drafts.sqlite3")
        self._drafts = DraftStore(draft_path) if draft_path else {}
        from decision_journal import DecisionJournal
        self.decision_journal = DecisionJournal(draft_path or str(Path(__file__).parent / "data" / "decisions.sqlite3"))
        self.graph = self._build()

    @staticmethod
    def _tags(state: AgentState, stage: str = "intent") -> dict:
        return {
            "account_id": state.get("account_id") or "",
            "run_id": state.get("run_id") or state.get("order_id") or "",
            "stage": stage,
        }

    def _shipping(self) -> tuple[float, float]:
        rules = getattr(self.mall, "rules", None) or {}
        try:
            return (
                float(rules.get("free_shipping_threshold", 400)),
                float(rules.get("shipping_fee_below_threshold", rules.get("shipping_fee", 30))),
            )
        except (TypeError, ValueError, AttributeError):
            return (400.0, 30.0)

    def _meal_context(self, state: AgentState) -> dict:
        caps = dict(state.get("policy_caps") or {})
        caps["monthly_spent"] = float(state.get("monthly_spent") or 0)
        return {
            "methods": (state.get("profile") or {}).get("payment_methods"),
            "benefit_rank": _benefit_rank(state),
            "caps": caps,
            "shipping": self._shipping(),
        }

    def _enrich_meal(self, state: AgentState, decision: dict, catalog: list[dict]) -> dict:
        """Let the model explain the optimiser's basket. Validate everything it says."""
        meal = dict(decision.get("meal") or {})
        steps = list(decision.get("react_steps") or [])
        if self.enricher is None or not decision.get("needs"):
            meal["llm"] = {"used": False, "reason": "no enricher configured"}
            return {**decision, "meal": meal, "llm_react": steps}
        by_sku = {str(row.get("id")): row for row in catalog}
        brief = {
            "request": meal.get("request"),
            "ceiling_hkd": meal.get("ceiling"),
            "minimum_hkd": meal.get("minimum"),
            "strategy": meal.get("strategy"),
            "coverage": meal.get("coverage"),
            "payment": [
                {key: row.get(key) for key in ("merchant", "label", "route", "amount", "benefits")}
                for row in meal.get("payment") or []
            ],
            "benefit_rank": _benefit_rank(state),
            "planned_charge_hkd": meal.get("planned_total"),
            "lines": [
                {
                    "sku": need["sku"],
                    "name": (by_sku.get(need["sku"]) or {}).get("name") or need.get("query"),
                    "group": need.get("group"),
                    "qty": need.get("qty"),
                    "unit_price_hkd": (by_sku.get(need["sku"]) or {}).get("price"),
                }
                for need in decision["needs"]
            ],
        }
        try:
            enriched = self.enricher(state["intent"], brief)
        except Exception as exc:  # no key, network, bad JSON: the optimiser result stands
            meal["llm"] = {"used": False, "reason": str(exc)[:200]}
            return {**decision, "meal": meal, "llm_react": steps}
        checked = enriched.get("parse_check") or {}
        request = meal.get("request") or {}
        overrides = {}
        agreement = {}
        for key, field, source in (("days", "days", "days_source"), ("family_size", "family", "family_source")):
            seen = checked.get(key)
            if not seen:
                continue
            mine = request.get(key)
            agreement[key] = {"optimizer": mine, "llm": seen["value"], "grounded": seen["grounded"]}
            # Only a value the sentence really contains can replace a default.
            if seen["grounded"] and request.get(source) == "default" and seen["value"] != mine and 0 < seen["value"] <= 31:
                overrides[field] = int(seen["value"])
                overrides[source] = "llm"
        for key, mine in (("max_hkd", request.get("max_total")), ("min_hkd", request.get("min_total"))):
            seen = checked.get(key)
            if seen:
                agreement[key] = {"optimizer": mine, "llm": seen["value"], "grounded": seen["grounded"]}
        if overrides:
            redone = plan_meal(state["intent"], catalog, overrides=overrides, **self._meal_context(state))
            if redone.get("needs"):
                decision = redone
                meal = dict(redone.get("meal") or {})
                steps = list(redone.get("react_steps") or [])
        notes = enriched.get("notes") or {}
        needs = []
        for need in decision["needs"]:
            note = notes.get(need["sku"])
            if note:
                need = {**need, "reason": f"{need['reason']} Meal idea (model): {note}"}
            needs.append(need)
        meal["llm"] = {
            "used": True,
            "model": enriched.get("model"),
            "notes": len(notes),
            "dropped": enriched.get("dropped", 0),
            "parse_check": agreement,
            "overrides": {k: v for k, v in overrides.items() if not k.endswith("_source")},
            "summary": enriched.get("summary") or "",
        }
        reply = str(decision.get("reply") or "")
        if enriched.get("summary"):
            reply = f"{reply} Model note: {enriched['summary']}"
        return {
            **decision,
            "needs": needs,
            "reply": reply,
            "meal": meal,
            "model": f"meal+llm:{enriched.get('model')}",
            "llm_react": [*(enriched.get("react") or []), *steps],
        }

    def _draft_basket(self, *, settlement: dict, account_id: str, intent: str, sku: str = "", qty: int = 1) -> dict | None:
        groups = settlement.get("merchants") or []
        if not self.payments or not groups or any(not group.get("payment", {}).get("route") for group in groups):
            return None
        from benefits import current_rules
        if isinstance(self.payments, PaymentClient) and current_rules() is not None:
            paid_lines = [line for group in groups for line in group.get("lines", []) if not line.get("is_gift")]
            return self.payments._request("POST", "/payment/basket/draft", {
                "account_id": account_id, "intent": intent,
                "groups": [{"merchant": group["merchant"], "amount": group["payment"]["amount"],
                            "rail": group["payment"]["route"]} for group in groups],
                "lines": [{"sku": line["sku"], "qty": line["qty"]} for line in paid_lines],
            })
        if len(groups) > 1 and hasattr(self.payments, "draft_basket"):
            return self.payments.draft_basket(account_id=account_id, intent=intent, groups=groups)
        return self.payments.draft(amount=float(settlement["total"]), merchant=groups[0]["merchant"],
                                   account_id=account_id, intent=intent, sku=sku, qty=qty,
                                   rail=groups[0]["payment"]["route"])

    def basket_alternatives(self, intent: str, sku: str, exclude_skus: list[str] | None = None) -> list[dict]:
        """Swap options for one basket line, taken from the real catalog only."""
        return meal_alternatives(intent, sku, self._catalog(), exclude=set(exclude_skus or []))

    def _catalog(self) -> list[dict]:
        products = getattr(self.mall, "products", None)
        if isinstance(products, list) and products:
            return products
        return self.mall.search("")

    def _merge_catalog(self, rows: list[dict]) -> None:
        if not isinstance(self.mall, FileMall):
            return
        existing = {row["id"]: row for row in self.mall.products}
        existing.update({row["id"]: row for row in rows})
        self.mall.products = list(existing.values())
        self.mall._by_sku = existing

    def _search_live_catalog(self, **arguments) -> dict:
        if self.profile is None or not hasattr(self.profile, "search_catalog"):
            raise ValueError("Live MySQL catalog search is unavailable; no demo catalog was substituted.")
        arguments = {key: ("" if value is None else value) for key, value in arguments.items()}
        page = self.profile.search_catalog(**arguments)
        self._merge_catalog(page["products"])
        return page

    def _resolve_monthly_spent(self, account_id: str, fallback: float) -> float:
        """MySQL spend is source of truth when persistence :8003 is up."""
        if self.spend is None:
            return float(fallback or 0)
        stored = self.spend.get_monthly_spent(account_id)
        if stored is None:
            return float(fallback or 0)
        return float(stored)

    def _load_profile(self, account_id: str) -> dict | None:
        if self.profile is None:
            return None
        try:
            found = self.profile.get_profile(account_id)
        except Exception:
            return None
        return found if isinstance(found, dict) else None

    def _open_order(self, account_id: str, intent: str, shopper: dict | None) -> str | None:
        if self.profile is None or not shopper:
            return None
        try:
            return self.profile.open_order(account_id, intent)
        except Exception:
            return None

    def _save_workflow(self, state: AgentState, step: str, extra: dict | None = None) -> None:
        if self.profile is None:
            return
        order_id = (extra or {}).get("order_id") or state.get("order_id")
        if not order_id:
            return
        view = dict(state)
        if extra:
            view.update(extra)
        product = view.get("product") or {}
        payment = view.get("payment") or {}
        try:
            self.profile.checkpoint(
                order_id,
                step=step,
                status=_workflow_status(step, view),
                snapshot=_order_snapshot(view, step),
                amount=_order_amount(view),
                merchant=product.get("merchant") or None,
                payment_route=view.get("payment_route") or None,
                payment_id=payment.get("order_id"),
                escalation_id=view.get("escalation_id") or None,
                lines=_order_lines(view),
            )
        except Exception:
            return

    def _remember(self, account_id: str, order_id: str | None, intent: str, plan: dict) -> None:
        if self.profile is None:
            return
        text = plan.get("reply") or plan.get("question") or ""
        if not text and isinstance(plan.get("policy"), dict):
            text = plan["policy"].get("reason") or ""
        if not text:
            text = plan.get("status") or "done"
        try:
            self.profile.append_chat(account_id, "user", intent, order_id or None)
            self.profile.append_chat(account_id, "assistant", text, order_id or None)
        except Exception:
            return

    def _live_rules(self) -> dict | None:
        if self.profile is None:
            return None
        if hasattr(self.profile, "http"):
            response = self.profile.http.get("/market/rules", timeout=15.0)
            response.raise_for_status()
            snapshot = response.json()
            if "promotions" not in snapshot:
                promotions = [{"id": f"merchant-{index}", "kind": "percent", "merchant": row["merchant"],
                               "threshold": row["threshold"], "rate": float(row["percent"]) / 100,
                               "enabled": True} for index, row in enumerate(snapshot.get("merchant_discounts", []))]
                for index, row in enumerate(snapshot.get("sku_gifts", [])):
                    item = self.profile.http.get(f"/catalog/products/{row['sku']}", timeout=15.0)
                    item.raise_for_status()
                    product = item.json()
                    self._merge_catalog([product])
                    promotions.append({"id": f"gift-{index}", "kind": "bogo", "merchant": product["merchant"],
                                       "sku": row["sku"], "threshold": 0, "enabled": True,
                                       "buy_qty": 1, "gift_qty": 1})
                snapshot = {**snapshot, "promotions": promotions}
            return snapshot
        if hasattr(self.profile, "market_rules"):
            return self.profile.market_rules()
        return None

    def run(self, intent: str, monthly_spent: float, escalation_id: str | None,
            account_id: str | None = None) -> dict:
        from benefits import rules_context
        try:
            rules = self._live_rules()
        except Exception as exc:
            return _plan_shell(intent, "FAILED", reply=f"Shared market rules are unavailable: {exc}")
        if rules is not None:
            with rules_context(rules):
                return self._run_impl(intent, monthly_spent, escalation_id, account_id)
        return self._run_impl(intent, monthly_spent, escalation_id, account_id)

    def _run_impl(
        self,
        intent: str,
        monthly_spent: float,
        escalation_id: str | None,
        account_id: str | None = None,
    ) -> dict:
        account = (account_id or os.environ.get("ACCOUNT_ID") or "demo").strip() or "demo"
        shopper = self._load_profile(account)
        if shopper is not None and shopper.get("monthly_spent") is not None:
            spent = float(shopper["monthly_spent"])
        else:
            spent = self._resolve_monthly_spent(account, monthly_spent)
        order_id = self._open_order(account, intent, shopper)
        result = self.graph.invoke(
            {
                "intent": intent,
                "monthly_spent": spent,
                "account_id": account,
                "escalation_id": escalation_id or "",
                "order_id": order_id or "",
                "run_id": order_id or "run_" + uuid.uuid4().hex[:12],
                "profile": shopper or {},
                "policy_caps": _caps_from(shopper),
                "preview_only": bool(_PREVIEW_ONLY.search(intent)),
                "user_max_total": _user_max_total(intent),
                "path": [],
                "audit_log": [],
            }
        )
        plan = {
            "intent": result.get("intent", intent),
            "status": result.get("plan_status", "FAILED"),
            "goal": result.get("goal"),
            "product": result.get("product"),
            "quote": result.get("quote"),
            "policy": result.get("policy"),
            "escalation": public_escalation(result["escalation"]) if result.get("escalation") else None,
            "payment": result.get("payment"),
            "payment_draft": result.get("payment_draft"),
            "settlement": result.get("settlement"),
            "suggestion": result.get("suggestion"),
            "lines": result.get("lines") or [],
            "repairs": result.get("repairs") or [],
            "payment_route": result.get("payment_route") or "",
            "payment_reason": result.get("payment_reason") or "",
            "question": result.get("question") or "",
            "reply": result.get("reply") or "",
            "react": build_react(result.get("audit_log") or [], result.get("goal"), result.get("llm_react")),
            "meal": result.get("meal"),
            "audit_log": result.get("audit_log", []),
        }
        plan = ActionPlan.model_validate(plan).model_dump()
        self._remember(account, result.get("order_id") or order_id, intent, plan)
        return plan

    def _audit(self, name: str):
        def audit(state: AgentState) -> dict:
            queued = state.get("policy_events") if name == "audit_policy" else None
            if name == "audit_intent" and state.get("decision_events"):
                queued = [*state["decision_events"], state["pending_event"]]
            if queued:
                log = list(state.get("audit_log") or [])
                stamped = []
                for pending in queued:
                    entry = _stamp(log + stamped, pending)
                    self.policy.log_event(entry["event"], entry["status"], entry["reason"])
                    stamped.append(entry)
                self._save_workflow(state, name)
                return {"path": [name], "audit_log": stamped}
            pending = state["pending_event"]
            entry = _stamp(state.get("audit_log", []), pending)
            self.policy.log_event(entry["event"], entry["status"], entry["reason"])
            self._save_workflow(state, name)
            return {"path": [name], "audit_log": [entry]}

        audit.__name__ = name
        return audit

    def _route_entry(self, state: AgentState) -> dict:
        escalation_id = state.get("escalation_id") or ""
        if not escalation_id:
            return {"path": ["route_entry"]}
        record = self.policy.get_escalation(escalation_id)
        if record is None or (record.get("account_id") and record["account_id"] != state.get("account_id")):
            return {
                "path": ["route_entry"],
                "escalation_status": "UNKNOWN",
            }
        snapshot = self._drafts.get(escalation_id) or {}
        if snapshot and snapshot.get("account_id") != state.get("account_id"):
            return {"path": ["route_entry"], "escalation_status": "UNKNOWN"}
        update: dict = {
            "path": ["route_entry"],
            "escalation_status": record.get("status"),
            "escalation": record,
        }
        for key in ("lines", "quote", "settlement", "product", "goal", "intent"):
            if snapshot.get(key) is not None:
                update[key] = snapshot[key]
        if record.get("product"):
            update["product"] = record["product"]
        if record.get("quote"):
            update["quote"] = record["quote"]
        if record.get("goal"):
            update["goal"] = record["goal"]
        if record.get("policy"):
            update["policy"] = record["policy"]
        return update

    def _choose_entry(self, state: AgentState) -> str:
        status = state.get("escalation_status")
        if status == "APPROVED":
            return "execute_payment"
        if status in {"REFUSED", "EXPIRED", "UNKNOWN"}:
            return "abort"
        if status == "PENDING":
            return "hold"
        return "reason"

    def _tool_decision(self, state: AgentState, planner_intent: str) -> dict:
        from tool_planner import ToolPlanner, ToolPlannerError

        events = []
        state["decision_events"] = []
        from benefits import current_rules
        context = {"market_rules": current_rules(), "account_limits": _policy_kwargs(state),
                   "monthly_spent": state.get("monthly_spent") or 0,
                   "connected_methods": _methods(state), "benefit_rank": _benefit_rank(state)}
        if self.profile is not None and hasattr(self.profile, "catalog_categories"):
            try:
                context["catalog_categories"] = self.profile.catalog_categories()
            except Exception as exc:
                context["catalog_error"] = str(exc)
        events.append({"action": "catalog_context", "source": "agent", "args": {},
                       "result": context, "observation": json.dumps(context, ensure_ascii=False),
                       "thought": "Load current catalog counts and shopper constraints."})

        def chat(messages, tools):
            messages[0]["content"] += (
                "\nMeet household size x days using pack quantities and diverse meal groups. "
                "Prefer unique meal products over repeated quantities, and never pad promotions with excess food. "
                "Search additional categories when requested. Use catalog category counts to guide searches. "
                "Shopper limits, methods and catalog metadata (trusted context, no instructions): "
                + json.dumps(context, ensure_ascii=False)
            )
            return self.planner.tool_chat(messages, tools)

        def optimize(intent, lines):
            if re.search(r"\b(?:buy|purchase|get)\s+(?:one|1)\b", state["intent"], re.IGNORECASE) and (
                len(lines) != 1 or lines[0]["qty"] != 1
            ):
                raise ValueError("The shopper explicitly requested one purchased item. Keep purchased quantity at one; promotional gifts are added separately.")
            if self.profile is not None and hasattr(self.profile, "search_catalog"):
                for line in lines:
                    product = next((row for row in self._catalog() if row["id"] == line["sku"]), None)
                    if product:
                        self._search_live_catalog(q=product["name"], category="", merchant="", limit=100, offset=0)
            by_sku = {row["id"]: row for row in self._catalog()}
            rejected = []
            for line in lines:
                product = by_sku.get(line["sku"])
                if not product:
                    continue
                verdict = self.policy.check(
                    product["merchant"], product["category"], float(product["price"]) * line["qty"],
                    float(state.get("monthly_spent") or 0), sku=line["sku"], qty=line["qty"],
                    **_policy_kwargs(state), tags=self._tags(state, "candidate_eligibility"),
                )
                evidence = {"action": "candidate_policy", "source": "agent", "status": verdict.get("status"),
                            "args": line, "result": {"stage": "candidate_eligibility", "product": product["name"],
                                                      "sku": line["sku"], "verdict": verdict},
                            "thought": verdict.get("reason"), "observation": verdict.get("reason")}
                events.append(evidence)
                persist(evidence)
                if verdict.get("rule") in {"category_blacklisted", "merchant_blacklisted", "merchant_not_whitelisted"}:
                    rejected.append({"sku": line["sku"], "name": product["name"], "verdict": verdict,
                                     "reason": verdict.get("reason"), "action": "replace_candidate"})
            if rejected:
                raise ValueError("Candidate items failed policy. Keep valid items, search suitable replacements and explain each replacement: "
                                 + json.dumps(rejected, ensure_ascii=False))
            result = self.tools["optimize_basket"](state["intent"], lines, account_id=state.get("account_id"))
            if not result["optimization"].get("feasible"):
                raise ValueError("No evaluated allocation fits stock, connected payment methods and the charged budget band. Revise the basket.")
            for selected in result["lines"]:
                if selected.get("is_gift"):
                    continue
                verdict = self.policy.check(selected["merchant"], selected["category"], selected["line_total"],
                                            float(state.get("monthly_spent") or 0), sku=selected["sku"],
                                            qty=selected["qty"], **_policy_kwargs(state),
                                            tags=self._tags(state, "optimized_eligibility"))
                if verdict.get("rule") in {"category_blacklisted", "merchant_blacklisted", "merchant_not_whitelisted"}:
                    raise ValueError(f"Optimized item {selected['sku']} failed policy: {verdict['reason']}. Search an allowed replacement.")
            return result

        journal_run = state.get("run_id") or state.get("order_id") or uuid.uuid4().hex
        def persist(event):
            self.decision_journal.append(journal_run, state.get("account_id") or "demo", event)
        persist(events[0])
        def record_event(event):
            events.append(event)
            persist(event)
        planner = ToolPlanner(chat, self._search_live_catalog, optimize,
                              model=getattr(self.planner, "model", None) or "llm-tools", on_event=record_event,
                              rules=current_rules())
        try:
            decision = planner(state["intent"])
        except ToolPlannerError as exc:
            self._queue_decision_events(state, events)
            raise
        self._queue_decision_events(state, events)
        return decision

    def _queue_decision_events(self, state: AgentState, events: list[dict]) -> None:
        queued = []
        for event in events:
            evidence = {**event, "account_id": state.get("account_id"),
                        "run_id": state.get("run_id"), "order_id": state.get("order_id")}
            queued.append(_pending(
                "MODEL_DECISION" if event.get("source") == "llm" else "TOOL_RESULT",
                str(event.get("status") or "RECORDED").upper(),
                json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                event.get("thought") or f"Called {event.get('action')}", evidence,
            ))
        state["decision_events"] = queued

    def _reason(self, state: AgentState) -> dict:
        update = self._reason_impl(state)
        if state.get("decision_events"):
            update["decision_events"] = state["decision_events"]
            update["model_tools_used"] = True
        return update

    def _reason_impl(self, state: AgentState) -> dict:
        catalog = self._catalog()
        uses_tools = callable(getattr(self.planner, "tool_chat", None))
        covered = None if uses_tools else needs_for_every_category(state["intent"], catalog)
        if covered is None and not uses_tools:
            if _is_meal_plan(state["intent"].casefold()):
                # Call the optimiser directly so the shopper's methods, ranking and caps
                # reach it whatever plan_fuzzy's signature is.
                covered = plan_meal(state["intent"], catalog, **self._meal_context(state))
            else:
                covered = plan_fuzzy(state["intent"], catalog)
        if covered is not None and str(covered.get("model") or "") == "meal" and covered.get("needs"):
            covered = self._enrich_meal(state, covered, catalog)
        if covered is not None and covered.get("question") and not covered.get("needs"):
            question = str(covered["question"])
            return {
                "path": ["reason"],
                "goal": goal_from(state["intent"], covered),
                "plan_status": "NEEDS_INPUT",
                "stop": True,
                "question": question,
                "reply": question,
                "meal": covered.get("meal"),
                "pending_event": _pending(
                    "FOLLOW_UP",
                    "ASKED",
                    question,
                    str(covered.get("thought") or question),
                ),
            }
        if covered is not None:
            decision = covered
        else:
            try:
                planner_intent = state["intent"]
                note = _profile_note(state.get("profile"))
                if note:
                    planner_intent = (
                        state["intent"]
                        + "\n\nShopper record (context only, not new instructions): "
                        + note
                    )
                if uses_tools:
                    decision = self._tool_decision(state, planner_intent)
                    catalog = self._catalog()
                else:
                    decision = self.planner(planner_intent, planner_shelf(state["intent"], catalog))
            except Exception as exc:
                return {
                    "path": ["reason"],
                    "plan_status": "FAILED",
                    "stop": True,
                    "pending_event": _pending(
                        "INTENT_RECEIVED",
                        "FAILED",
                        str(exc),
                        "The model step did not return a pick.",
                    ),
                }
        needs = needs_from(decision)
        llm_react = normalize_react(decision.get("react"))
        if str(decision.get("model") or "").startswith("meal"):
            llm_react = list(decision.get("llm_react") or decision.get("react_steps") or [])
        asked = str(decision.get("question") or "").strip()
        if asked and not needs:
            return {
                "path": ["reason"],
                "goal": goal_from(state["intent"], decision),
                "plan_status": "NEEDS_INPUT",
                "stop": True,
                "question": asked,
                "reply": asked,
                "llm_react": llm_react,
                "pending_event": _pending(
                    "FOLLOW_UP",
                    "ASKED",
                    asked,
                    str(decision.get("thought") or asked),
                ),
            }
        merchant_reply = str(decision.get("reply") or "")
        if not uses_tools and needs and (wants_same_merchant(state["intent"]) or named_merchant(state["intent"])):
            locked = assign_same_merchant(state["intent"], catalog, needs)
            merchant_reply = _join_reply(str(decision.get("reply") or ""), locked["reply"])
            needs = locked["needs"]
            if not needs:
                return {
                    "path": ["reason"],
                    "goal": goal_from(state["intent"], decision),
                    "plan_status": "FAILED",
                    "stop": True,
                    "reply": merchant_reply,
                    "pending_event": _pending(
                        "INTENT_RECEIVED",
                        "FAILED",
                        "No product matched",
                        merchant_reply,
                    ),
                }
        if len(needs) >= 2 or merchant_reply or (uses_tools and needs):
            missing = [need["query"] for need in needs if not options_for(self._catalog(), need)]
            if missing:
                return {
                    "path": ["reason"],
                    "goal": goal_from(state["intent"], decision),
                    "plan_status": "FAILED",
                    "stop": True,
                    "pending_event": _pending(
                        "INTENT_RECEIVED",
                        "FAILED",
                        "No product matched",
                        str(decision.get("thought") or "Nothing on the shelf fit the sentence."),
                    ),
                }
            goal = goal_from(
                state["intent"],
                {
                    "query": ", ".join(need["query"] for need in needs),
                    "qty": len(needs),
                    "thought": _join_reply(
                        decision.get("thought") or "Several items. Code fits them to policy.",
                        merchant_reply,
                    ),
                    "model": decision.get("model") or "",
                },
            )
            if merchant_reply:
                named = "Same-merchant request. Code picked the shop. Policy still judges every line."
            elif str(decision.get("model") or "").startswith("meal"):
                named = (
                    "Meal-plan optimiser: code read the budget band, days and family size, "
                    "picked SKUs and quantities from the catalog, and ranked payment by your benefits."
                )
            elif decision.get("model") == "catalog":
                named = "One item from each catalog category. Code fits the basket to policy."
            else:
                named = "Model may name each need. Code fits the basket to policy."
            update = {
                "path": ["reason"],
                "goal": goal,
                "needs": needs,
                "reply": merchant_reply,
                "llm_react": llm_react,
                "pending_event": _pending("INTENT_RECEIVED", "PARSED", named, goal["thought"]),
            }
            if decision.get("meal"):
                meal = decision["meal"]
                update["meal"] = meal
                ceiling = (meal.get("request") or {}).get("max_total")
                if ceiling is not None and state.get("user_max_total") is None:
                    update["user_max_total"] = float(ceiling)
            return update
        try:
            chosen = resolve_pick(self._catalog(), decision)
        except Exception as exc:
            return {
                "path": ["reason"],
                "plan_status": "FAILED",
                "stop": True,
                "pending_event": _pending(
                    "INTENT_RECEIVED",
                    "FAILED",
                    str(exc),
                    "The model step did not return a pick.",
                ),
            }
        if chosen is None:
            return {
                "path": ["reason"],
                "goal": goal_from(state["intent"], decision),
                "plan_status": "FAILED",
                "stop": True,
                "pending_event": _pending(
                    "INTENT_RECEIVED",
                    "FAILED",
                    "No product matched",
                    str(decision.get("thought") or "Nothing on the shelf fit the sentence."),
                ),
            }
        goal = goal_from(state["intent"], decision, chosen)
        return {
            "path": ["reason"],
            "goal": goal,
            "product": _product(chosen),
            "llm_react": llm_react,
            "pending_event": _pending(
                "INTENT_RECEIVED",
                "PARSED",
                "Model may decide query, qty, and sell point",
                goal["thought"],
            ),
        }

    def _after_intent(self, state: AgentState) -> str:
        return "end" if state.get("stop") else "plan"

    def _plan(self, state: AgentState) -> dict:
        meal = state.get("meal") or {}
        thought = None
        if meal.get("strategy"):
            thought = (
                f"Price the {len(state.get('needs') or [])} optimiser lines from {meal['strategy']}, "
                f"then let the policy engine judge every line and the total before the shopper sees it."
            )
        return {
            "path": ["plan"],
            "pending_event": _pending(
                "PLAN",
                "FIXED_ORDER",
                "search_products, price_cart, check_budget, then the policy branch",
                thought,
            ),
        }

    def _search(self, state: AgentState) -> dict:
        if state.get("needs"):
            count = len(state["needs"])
            thought = f"Shelf search kept {count} products."
            groups: dict[str, int] = {}
            for need in state["needs"]:
                if need.get("group"):
                    groups[need["group"]] = groups.get(need["group"], 0) + 1
            if groups:
                thought = (
                    f"All {count} SKUs exist in the catalog with a live price: "
                    + ", ".join(f"{name} {n}" for name, n in groups.items())
                    + "."
                )
            return {
                "path": ["search_products"],
                "pending_event": _pending(
                    "SEARCH",
                    "RECORDED",
                    f"Basket of {count} needs.",
                    thought,
                ),
            }
        chosen = state.get("product") or {}
        sku = chosen.get("id") or (state.get("goal") or {}).get("sku")
        try:
            fresh = self.mall.product(sku)
        except Exception:
            return _failure("search_products", "SEARCH", "Mall search failed")
        goal = state.get("goal") or {}
        sell = goal.get("sell_point") or fresh.get("sell_point") or ""
        need = {
            "query": goal.get("query") or fresh.get("name") or "",
            "sell_point": sell,
            "qty": goal.get("qty") or 1,
            "priority": 1,
        }
        options = options_for(self._catalog(), need) or [fresh]
        if not any(item.get("id") == fresh.get("id") for item in options):
            options = [fresh, *options]
        detail = explain_pick(need, fresh, options, _methods(state), _benefit_rank(state))
        thought = detail
        return {
            "path": ["search_products"],
            "product": _product(fresh),
            "pending_event": _pending(
                "SEARCH",
                "RECORDED",
                f"Picked {fresh['id']} for sell point {sell}.",
                thought,
            ),
        }

    def _after_search(self, state: AgentState) -> str:
        return "end" if state.get("stop") else "price_cart"

    def _cart(self, state: AgentState) -> dict:
        if state.get("needs"):
            return self._price_basket(state)
        product = state["product"]
        qty = int(state["goal"]["qty"])
        try:
            quoted = self.mall.cart(product["id"], qty)
            _verify_cart_quote(quoted, [{"sku": product["id"], "qty": qty}], [product])
        except ValueError as exc:
            return _failure("price_cart", "CART_PRICED", str(exc))
        except Exception:
            return _failure("price_cart", "CART_PRICED", "Mall cart failed")
        return {
            "path": ["price_cart"],
            "quote": _quote(quoted),
            "pending_event": _pending(
                "CART_PRICED",
                "RECORDED",
                "Later nodes use total_landed_cost, not the shelf price.",
            ),
        }

    def _price_basket(self, state: AgentState) -> dict:
        caps = _policy_kwargs(state)

        def policy_check(lines, amount, spent):
            return self.policy.check_lines(lines, amount, spent, **caps, tags=self._tags(state))

        try:
            fitted = fit_basket(
                self._catalog(),
                state["needs"],
                float(state.get("monthly_spent") or 0),
                self.mall.cart_lines,
                policy_check,
                methods=_methods(state),
                benefit_rank=_benefit_rank(state),
            )
        except Exception:
            return _failure("price_cart", "CART_PRICED", "Mall cart failed")
        allocation_step = None
        if not state.get("model_tools_used") and not state.get("meal") and fitted["lines"] and not any(need.get("merchant") for need in state["needs"]):
            try:
                optimized = self.tools["optimize_basket"](
                    state["intent"], fitted["lines"], account_id=state.get("account_id"),
                )
                allocation_step = {"thought": "Compare merchant allocations for the requested items.",
                                   "action": "optimize_basket", "source": "optimizer",
                                   "observation": optimized["optimization"]["explanation"]}
                if optimized["optimization"]["feasible"] and any(
                    old["sku"] != new["sku"] for old, new in zip(fitted["lines"], optimized["lines"])
                ):
                    needs = [{"sku": line["sku"], "query": line["name"], "qty": line["qty"],
                              "priority": index + 1, "reason": f"Same product and quantity; {line['merchant']} was selected by the whole-basket cost comparison."}
                             for index, (old, line) in enumerate(zip(fitted["lines"], optimized["lines"]))]
                    fitted = fit_basket(self._catalog(), needs, float(state.get("monthly_spent") or 0),
                                        self.mall.cart_lines, policy_check, methods=_methods(state),
                                        benefit_rank=_benefit_rank(state))
            except ValueError as exc:
                return _failure("price_cart", "CART_PRICED", str(exc))
        try:
            requested = [{"sku": line["sku"], "qty": int(line["qty"])} for line in fitted["lines"]]
            _verify_cart_quote(fitted["quote"], requested, self._catalog())
        except ValueError as exc:
            return _failure("price_cart", "CART_PRICED", str(exc))
        first = fitted["lines"][0]
        fresh = self.mall.product(first["sku"])
        route = fitted["payment_route"]
        route_reason = fitted["payment_reason"]
        meal = state.get("meal") or {}
        if meal.get("payment"):
            chosen = meal["payment"][0]
            route = chosen.get("route") or route
            route_reason = (
                f"{chosen.get('label')} chosen by benefits.quote_tender from your connected methods for "
                + ", ".join(f"{row.get('merchant')} ({row.get('label')})" for row in meal["payment"])
                + "."
            )
        quote = _quote(fitted["quote"])
        return {
            "path": ["price_cart"],
            "quote": quote,
            "product": _product(fresh),
            "lines": fitted["lines"],
            "repairs": fitted["repairs"],
            "llm_react": [*(state.get("llm_react") or []), *([allocation_step] if allocation_step else [])],
            "question": fitted["question"],
            "reply": _join_reply(state.get("reply") or "", fitted.get("reply") or ""),
            "payment_route": route,
            "payment_reason": route_reason,
            "basket_policy": fitted["policy"],
            "policy_events": fitted["events"],
            "pending_event": _pending(
                "CART_PRICED",
                "RECORDED",
                fitted["cart_reason"],
                (
                    f"Mall priced {len(fitted['lines'])} lines: goods HK${quote['subtotal']:.2f}, "
                    f"shipping HK${quote['shipping_fee']:.2f}, landed HK${quote['total_landed_cost']:.2f}."
                ),
            ),
        }

    def _after_cart(self, state: AgentState) -> str:
        if state.get("stop"):
            return "end"
        maximum = state.get("user_max_total")
        quote = state.get("quote") or {}
        landed = _finite_money(quote.get("total_landed_cost"))
        if maximum is not None and landed is not None and landed > maximum:
            return "user_limit"
        return "check_budget"

    def _user_limit(self, state: AgentState) -> dict:
        maximum = float(state["user_max_total"])
        total = float((state.get("quote") or {})["total_landed_cost"])
        reason = f"Quoted landed total HK${total:.2f} exceeds your HK${maximum:.2f} maximum."
        return {
            "path": ["user_limit"],
            "plan_status": "HALTED",
            "reply": reason,
            "pending_event": _pending("HALTED", "HALTED", reason),
        }

    def _budget(self, state: AgentState) -> dict:
        if state.get("needs"):
            result = state["basket_policy"]
            return {
                "path": ["check_budget"],
                "policy": result,
                "policy_status": result["status"],
            }
        product = state["product"]
        result = self.policy.check(
            merchant=product["merchant"],
            category=product["category"],
            amount=state["quote"]["total_landed_cost"],
            monthly_spent=state.get("monthly_spent", 0),
            sku=product["id"],
            qty=int(state["goal"]["qty"]),
            **_policy_kwargs(state),
            tags=self._tags(state),
        )
        return {
            "path": ["check_budget"],
            "policy": result,
            "policy_status": result["status"],
            "pending_event": _pending(
                "POLICY_CHECK",
                result["status"],
                result["reason"],
                engine_thought(result),
                policy_snapshot(result),
            ),
        }

    def _after_policy(self, state: AgentState) -> str:
        if state.get("stop"):
            return "end"
        if state.get("question"):
            return "ask"
        if state.get("preview_only"):
            return "preview"
        return {
            "PASS": "review",
            "ESCALATE": "create_escalation",
            "HALT": "halt",
        }[state["policy_status"]]

    def _review(self, state: AgentState) -> dict:
        policy = state.get("policy") or {}
        quote = state.get("quote") or {}
        authorized = _finite_money(quote.get("total_landed_cost"))
        if policy.get("status") == "PASS" and _finite_money(policy.get("amount")) != authorized:
            failed = _failure("review", "POLICY_CHECK", "Pay allowed only after PASS or APPROVED")
            self._save_workflow(state, "review", failed)
            return failed
        lines = _review_lines(state)
        settlement = settlement_for(lines, state.get("quote") or {}, _methods(state), _benefit_rank(state))
        from benefits import gift_lines
        lines = [*lines, *gift_lines(lines)]
        total = settlement.get("total")
        review = (
            f"Basket total HK${float(total):.2f}. "
            "Review the items, then confirm. I will check the rules again before payment."
        )
        prior = (state.get("reply") or "").strip()
        return {
            "path": ["review"],
            "plan_status": "READY",
            "payment": None,
            "lines": lines,
            "settlement": settlement,
            "reply": f"{prior} {review}".strip() if prior else review,
            "pending_event": _pending(
                "BASKET_REVIEW",
                "READY",
                "Basket is waiting for the shopper to confirm or edit it.",
                "Open the basket, change quantity or remove a line, then confirm.",
            ),
        }

    def optimize_basket(self, intent: str, lines: list[dict], account_id: str | None = None) -> dict:
        from benefits import current_rules, rules_context
        if current_rules() is None:
            rules = self._live_rules()
            if rules is not None:
                with rules_context(rules):
                    return self._optimize_basket_impl(intent, lines, account_id)
        return self._optimize_basket_impl(intent, lines, account_id)

    def _optimize_basket_impl(self, intent: str, lines: list[dict], account_id: str | None = None) -> dict:
        """Read-only tool: allocate existing item quantities across merchant offers."""
        from basket_optimizer import optimize_basket
        from meal_plan import parse_request, WHITELIST

        account = (account_id or os.environ.get("ACCOUNT_ID") or "demo").strip() or "demo"
        profile = self._load_profile(account) or {}
        request = parse_request(intent)
        allowed = set(request.merchants or WHITELIST)
        catalog = [row for row in self._catalog() if row.get("merchant") in allowed]
        by_id = {row["id"]: row for row in catalog}
        detailed = []
        for line in lines:
            sku = str(line.get("sku") or "")
            qty = int(line.get("qty") or 0)
            if sku not in by_id or qty < 1:
                raise ValueError("Each optimizer line needs an allowed catalog SKU and a positive quantity.")
            product = by_id[sku]
            detailed.append({"sku": sku, "name": product["name"], "merchant": product["merchant"],
                             "category": product["category"], "qty": qty,
                             "unit_price": product["price"], "line_total": round(product["price"] * qty, 2)})
        if not detailed:
            raise ValueError("The optimizer needs at least one basket item.")
        ceiling = min(float(profile.get("bulk_ceiling") or 800),
                      max(0, float(profile.get("monthly_cap") or 2000) - float(profile.get("monthly_spent") or 0)))
        if request.max_total is not None:
            ceiling = min(ceiling, request.max_total)
        return optimize_basket(detailed, catalog, methods=profile.get("payment_methods"),
                               rank=_benefit_rank({"profile": profile, "intent": intent}),
                               max_total=ceiling, min_total=request.min_total, shipping=self._shipping())

    def confirm_basket(self, intent: str, lines: list[dict], removed_skus: list[str] | None = None,
                       monthly_spent: float = 0, account_id: str | None = None) -> dict:
        from benefits import rules_context
        try:
            rules = self._live_rules()
        except Exception as exc:
            return _plan_shell(intent, "NEEDS_INPUT",
                               question=f"Shared market rules are unavailable: {exc}. Retry before payment.")
        if rules is not None:
            with rules_context(rules):
                return self._confirm_basket_impl(intent, lines, removed_skus, monthly_spent, account_id)
        return self._confirm_basket_impl(intent, lines, removed_skus, monthly_spent, account_id)

    def _confirm_basket_impl(
        self,
        intent: str,
        lines: list[dict],
        removed_skus: list[str] | None = None,
        monthly_spent: float = 0,
        account_id: str | None = None,
    ) -> dict:
        """Reprice the edited basket and run policy a second time. No charge yet."""
        account = (account_id or os.environ.get("ACCOUNT_ID") or "demo").strip() or "demo"
        profile = self._load_profile(account) or {}
        if profile.get("monthly_spent") is not None:
            # Stored spend is the source of truth, same as run(). The browser's
            # copy can be stale or missing (it defaulted to 0).
            monthly_spent = float(profile["monthly_spent"])
        else:
            monthly_spent = self._resolve_monthly_spent(account, monthly_spent)
        methods = connected_methods(profile.get("payment_methods"))
        rank = _benefit_rank({"profile": profile, "intent": intent})
        removed = {sku for sku in (removed_skus or []) if sku}
        if callable(getattr(self.planner, "tool_chat", None)) and self.profile is not None:
            for line in lines:
                sku = str(line.get("sku") or "")
                if sku:
                    page = self._search_live_catalog(q=sku, category="", merchant="", limit=100, offset=0)
                    if not any(row["id"] == sku for row in page["products"]):
                        return _plan_shell(intent, "NEEDS_INPUT", question=f"{sku} is no longer in the live catalog. Choose a replacement.")
        catalog = {row["id"]: row for row in self._catalog()}
        requested = []
        for line in lines:
            sku = str(line.get("sku") or "")
            if not sku or sku in removed:
                continue
            qty = max(1, int(line.get("qty") or 1))
            requested.append({"sku": sku, "qty": qty})
        if not requested:
            return _plan_shell(
                intent,
                "NEEDS_INPUT",
                question="The basket is empty. Tell me what to look for instead.",
                reply="The basket is empty. Tell me what to look for instead.",
            )
        try:
            quoted = self.mall.cart_lines(requested)
            _verify_cart_quote(quoted, requested, self._catalog())
        except ValueError as exc:
            return _plan_shell(intent, "FAILED", reply=str(exc))
        except Exception:
            return _plan_shell(intent, "FAILED", reply="Mall cart failed")
        quote = _quote(quoted)
        detailed = []
        for raw in quoted["line_items"]:
            product = catalog.get(raw["sku"]) or raw
            detailed.append(
                {
                    **raw,
                    "need": product.get("name") or raw.get("sku") or "",
                    "priority": 1,
                    "image_url": product.get("image_url") or "",
                    "name": raw.get("name") or product.get("name"),
                    "sell_point": product.get("sell_point") or "",
                    "product_reason": product.get("product_reason") or "",
                    "merchant_reason": product.get("merchant_reason") or "",
                }
            )
        meal = None
        settlement = settlement_for(detailed, quote, methods, rank)
        if is_meal_intent(intent):
            caps_now = dict(_caps_from(profile))
            caps_now["monthly_spent"] = float(monthly_spent or 0)
            described = describe_lines(
                intent,
                detailed,
                catalog,
                methods=profile.get("payment_methods"),
                benefit_rank=rank,
                caps=caps_now,
                quote=quote,
                settlement=settlement,
            )
            for line in detailed:
                reason = described["reasons"].get(line["sku"])
                if reason:
                    line["product_reason"] = reason
            meal = {
                "ceiling": described["ceiling"],
                "minimum": described["minimum"],
                "under_min": described["under_min"],
                "coverage": described["coverage"],
                "warnings": described["warnings"],
                "benefits": settlement.get("benefits") or [],
                "discount": settlement.get("discount") or 0,
                "payment": [
                    {
                        "merchant": group.get("merchant"),
                        "route": (group.get("payment") or {}).get("route"),
                        "label": (group.get("payment") or {}).get("label"),
                        "last4": (group.get("payment") or {}).get("last4"),
                        "amount": (group.get("payment") or {}).get("amount"),
                        "benefits": group.get("benefits") or [],
                        "because": group.get("because") or "",
                    }
                    for group in settlement.get("merchants") or []
                ],
            }
        confirm_run = "cfm_" + uuid.uuid4().hex[:12]
        result, events = self.policy.check_lines(
            detailed,
            quote["total_landed_cost"],
            float(monthly_spent or 0),
            **_policy_kwargs({"policy_caps": _caps_from(profile)}),
            tags={"account_id": account, "run_id": confirm_run, "stage": "confirm"},
        )
        from benefits import current_rules, gift_lines
        if current_rules() is not None:
            evidence = {"action": "confirm_market_quote", "stage": "confirm", "market_rules": current_rules(),
                        "settlement": settlement, "account_id": account, "run_id": confirm_run}
            events.insert(0, _pending("TOOL_RESULT", "RECORDED", json.dumps(evidence, sort_keys=True, ensure_ascii=False),
                                      "Reprice the user basket using the current shared market rules.", evidence))
        band_steps = _band_steps(meal, quote, settlement)
        if band_steps:
            # Visible in the agent's reasoning and the step trace, not only the pop-up.
            events = [
                *events,
                {
                    "event": "BASKET_REVISED",
                    "status": "UNDER_MINIMUM" if (meal or {}).get("under_min") else "IN_BAND",
                    "reason": band_steps[0]["observation"],
                    "thought": band_steps[0]["thought"],
                },
            ]
        if result.get("status") == "HALT":
            suggestion = _suggestion(self._catalog(), detailed, removed, result)
            question = _followup(result, suggestion)
            return _plan_shell(
                intent,
                "NEEDS_INPUT",
                quote=quote,
                lines=detailed,
                policy=result,
                question=question,
                reply=question,
                suggestion=suggestion,
                settlement=settlement,
                meal=meal,
                react=band_steps,
                audit=_policy_audit(result, events),
            )
        if meal and any("over your" in text for text in meal["warnings"]):
            # The policy engine passed, but the shopper's own maximum from the
            # sentence is a hard limit too. Send the basket back for edits.
            question = " ".join(meal["warnings"]) + " Remove an item or lower a quantity, then confirm again."
            return _plan_shell(
                intent,
                "NEEDS_INPUT",
                quote=quote,
                lines=detailed,
                policy={**result, "status": "HALT", "rule": "user_max_total", "reason": meal["warnings"][0]},
                question=question,
                reply=question,
                settlement=settlement,
                meal=meal,
                react=band_steps,
                audit=_policy_audit(result, events),
            )
        maximum = _user_max_total(intent)
        if maximum is not None and quote["total_landed_cost"] > maximum:
            reason = f"Quoted landed total HK${quote['total_landed_cost']:.2f} exceeds your HK${maximum:.2f} maximum."
            return _plan_shell(
                intent, "NEEDS_INPUT", quote=quote, lines=detailed,
                policy={**result, "status": "HALT", "rule": "user_max_total", "reason": reason},
                question=reason + " Remove an item or lower a quantity, then confirm again.",
                reply=reason, settlement=settlement, meal=meal,
                audit=_policy_audit(result, events),
            )
        escalation = None
        if result.get("status") == "ESCALATE":
            first = detailed[0]
            caps = _policy_kwargs({"policy_caps": _caps_from(profile)})
            escalation = self.policy.create_escalation(
                {
                    "amount": quote["total_landed_cost"],
                    "currency": "HKD",
                    "merchant": first.get("merchant") or "",
                    "category": first.get("category") or "",
                    "sku": first.get("sku") or "",
                    "qty": int(first.get("qty") or 1),
                    "reason": result.get("reason") or "",
                    "monthly_spent": float(monthly_spent or 0),
                    "account_id": account,
                    "run_id": confirm_run,
                    "order_id": confirm_run,
                    **caps,
                }
            )
        if escalation:
            first = detailed[0]
            self._drafts[escalation["escalation_id"]] = {
                "account_id": account, "intent": intent, "lines": detailed, "quote": quote,
                "settlement": settlement, "product": {**catalog[first["sku"]]},
                "goal": {"intent": intent, "query": first["name"], "qty": int(first["qty"])},
            }
        draft = None
        if result.get("status") == "PASS" and self.payments is not None:
            merchant = detailed[0].get("merchant") or ""
            held = self._draft_basket(
                settlement=settlement, account_id=account, intent=intent,
                sku=detailed[0].get("sku") or "", qty=int(detailed[0].get("qty") or 1),
            )
            if held and held.get("payment_id"):
                draft = {
                    "payment_id": held["payment_id"],
                    "status": held.get("status") or "DRAFT",
                    "amount": float(settlement["total"]),
                    "currency": "HKD",
                    "rail": held.get("rail") or "",
                    "merchant": merchant,
                    "risk_score": int(held.get("risk_score") or 0),
                    "step_up_required": bool(held.get("step_up_required")),
                    "step_up_reason": held.get("step_up_reason") or "",
                    "recommendation": held.get("recommendation"),
                }
                self._drafts[held["payment_id"]] = {
                    "account_id": account,
                    "intent": intent,
                    "lines": detailed,
                    "quote": quote,
                    "settlement": settlement,
                }
                # Pending and captured-but-unsaved baskets remain available for recovery.
        if result.get("status") == "PASS" and self.payments is not None and draft is None:
            return _plan_shell(intent, "NEEDS_INPUT", quote=quote, lines=detailed, policy=result,
                               settlement=settlement, meal=meal,
                               question="Payment service unavailable. Confirm the basket again when it recovers.",
                               reply="Payment service unavailable. The basket is saved for editing; no charge was made.",
                               audit=_policy_audit(result, events))
        status = "ESCALATED" if result.get("status") == "ESCALATE" else "READY"
        return _plan_shell(
            intent,
            status,
            quote=quote,
            lines=[*detailed, *gift_lines(detailed)],
            policy=result,
            settlement=settlement,
            payment_draft=draft,
            escalation=escalation,
            meal=meal,
            react=band_steps,
            reply=(
                f"Rules checked again. Amount to approve is HK${float(settlement['total']):.2f}."
                + (" " + " ".join(meal["warnings"]) if meal and meal.get("warnings") else "")
            ),
            audit=_policy_audit(result, events),
        )

    def approve_payment(
        self,
        *,
        amount: float,
        payment_id: str | None = None,
        step_up_confirmed: bool = False,
        account_id: str = "demo",
        payment_route: str = "mastercard",
        merchant: str = "",
    ) -> dict:
        """Charge only after the shopper approves. A mismatched gateway amount fails closed."""
        if self.payments is not None:
            if payment_id:
                return self.authorize_draft(payment_id, step_up_confirmed=step_up_confirmed, account_id=account_id)
            return {"success": False, "order_id": None, "charged": None, "currency": "HKD",
                    "payment_route": payment_route, "ts": None, "error": "payment_draft_required", "payment_id": None}
        authorized = _finite_money(amount)
        if authorized is None:
            return {
                "success": False,
                "order_id": None,
                "charged": None,
                "currency": None,
                "payment_route": None,
                "ts": None,
                "error": "Missing amount",
                "payment_id": payment_id,
            }
        try:
            result = self.mall.pay(authorized, idempotency_key=payment_id or f"approve:{authorized}", payment_route=payment_route)
        except Exception:
            return {
                "success": False,
                "order_id": None,
                "charged": None,
                "currency": None,
                "payment_route": payment_route,
                "ts": None,
                "error": "Mall pay failed",
                "payment_id": payment_id,
            }
        charged = _finite_money(result.get("charged"))
        if result.get("success") and (charged != authorized or (result.get("currency") or "HKD") != "HKD"):
            received = f"HK${charged:.2f}" if charged is not None else "an unknown amount"
            result = {
                **result,
                "success": False,
                "error": (
                    f"Payment response mismatch: authorized HK${authorized:.2f}, "
                    f"but the gateway reported {received}."
                ),
            }
        result["payment_id"] = payment_id
        result.setdefault("payment_route", payment_route)
        return result

    def _preview(self, state: AgentState) -> dict:
        return {
            "path": ["preview"],
            "plan_status": "READY",
            "payment": None,
            "reply": "Quote is ready; no purchase was made.",
            "pending_event": _pending(
                "PREVIEW_READY",
                "READY",
                "Shopper requested a quote without checkout.",
            ),
        }

    def _pay(self, state: AgentState) -> dict:
        approved = state.get("escalation_status") == "APPROVED"
        policy = state.get("policy") or {}
        quote = state.get("quote") or {}
        escalation = state.get("escalation") or {}
        authorized_total = _finite_money(quote.get("total_landed_cost"))
        if authorized_total is None and escalation.get("amount") is not None:
            authorized_total = _finite_money(escalation.get("amount"))
        valid_total = authorized_total is not None and authorized_total >= 0
        passed = (
            (state.get("policy_status") == "PASS" or policy.get("status") == "PASS")
            and policy.get("status") == "PASS"
            and valid_total
            and _finite_money(policy.get("amount")) == authorized_total
        )
        if not valid_total:
            failed = _failure("execute_payment", "PAYMENT", "Missing or invalid verified landed total")
            self._save_workflow(state, "execute_payment", failed)
            return failed
        if not approved and not passed:
            failed = _failure("execute_payment", "PAYMENT", "Pay allowed only after PASS or APPROVED")
            self._save_workflow(state, "execute_payment", failed)
            return failed
        if approved and (
            escalation.get("status") != "APPROVED"
            or _finite_money(escalation.get("amount")) != authorized_total
        ):
            failed = _failure(
                "execute_payment",
                "PAYMENT",
                "Approved escalation amount does not match the verified quote",
            )
            self._save_workflow(state, "execute_payment", failed)
            return failed
        product = state.get("product") or {}
        goal = state.get("goal") or {}
        sku = product.get("id") or escalation.get("sku")
        qty = goal.get("qty") or 1
        tag = "PASS" if passed and not approved else "ESCALATE"
        escalation_id = state.get("escalation_id") or "none"
        if tag == "PASS":
            escalation_id = "none"
        connected = str((state.get("profile") or {}).get("default_payment_route") or "").strip()
        route = connected or state.get("payment_route") or "mastercard"
        merchant = str(product.get("merchant") or escalation.get("merchant") or "unknown")
        key = f"{sku}:{qty}:{tag}:{escalation_id}"
        if self.payments is not None:
            settlement = state.get("settlement") or settlement_for(_review_lines(state), quote, _methods(state), _benefit_rank(state))
            draft = self._draft_basket(
                settlement=settlement, account_id=state.get("account_id") or "demo",
                intent=str(state.get("intent") or ""), sku=str(sku or ""), qty=int(qty),
            )
            if draft and draft.get("payment_id"):
                self._drafts[draft["payment_id"]] = {
                    "account_id": state.get("account_id") or "demo",
                    "intent": state.get("intent") or "",
                    "lines": _review_lines(state),
                    "quote": quote,
                    "approved_escalation": escalation_id if approved else None,
                    "settlement": settlement,
                }
                held = {
                    "path": ["execute_payment"],
                    "plan_status": "READY",
                    "payment": None,
                    "payment_route": draft.get("rail") or route,
                    "settlement": settlement,
                    "lines": _review_lines(state),
                    "payment_draft": {
                        "payment_id": draft["payment_id"],
                        "status": draft.get("status") or "DRAFT",
                        "amount": float(draft.get("amount") if draft.get("amount") is not None else authorized_total),
                        "currency": draft.get("currency") or "HKD",
                        "rail": draft.get("rail") or route,
                        "merchant": draft.get("merchant") or merchant,
                        "risk_score": int(draft.get("risk_score") or 0),
                        "step_up_required": bool(draft.get("step_up_required")),
                        "step_up_reason": draft.get("step_up_reason") or "",
                        "recommendation": draft.get("recommendation"),
                    },
                    "reply": "Draft held until the shopper authorizes.",
                    "pending_event": _pending(
                        "PAYMENT",
                        "DRAFT",
                        "Draft held until the shopper authorizes.",
                    ),
                }
                self._save_workflow(state, "execute_payment", held)
                return held
            return _failure("execute_payment", "PAYMENT", "Payment service unavailable. Retry to create a draft before approving.")
        try:
            payment = self.mall.pay(authorized_total, key, route)
        except Exception:
            return _failure("execute_payment", "PAYMENT", "Mall payment failed")
        actual_charge = _finite_money(payment.get("charged"))
        charge_matches = bool(payment.get("success")) and actual_charge == authorized_total and (
            payment.get("currency") == quote.get("currency", "HKD")
        )
        plan_status = "COMPLETED" if charge_matches else "FAILED"
        if charge_matches:
            reason = "Payment success"
        elif payment.get("success"):
            received = f"HK${actual_charge:.2f}" if actual_charge is not None else "an unknown amount"
            reason = (
                f"Payment response mismatch: authorized HK${authorized_total:.2f}, "
                f"but the gateway reported {received}. Verify the charge before retrying."
            )
        else:
            reason = payment.get("error") or "Payment failed"
        if charge_matches and self.spend is not None:
            order_id = payment.get("order_id") or key
            self.spend.record_payment(
                float(actual_charge),
                account_id=state.get("account_id") or "demo",
                payment_id=payment.get("order_id"),
                idempotency_key=str(order_id),
                note=f"intent={state.get('intent') or ''}",
            )
        paid = {
            "path": ["execute_payment"],
            "payment": payment,
            "plan_status": plan_status,
            "payment_route": route,
            "reply": reason if payment.get("success") and not charge_matches else (state.get("reply") or ""),
            "pending_event": _pending("PAYMENT", "COMPLETED" if charge_matches else "FAILED", reason),
        }
        self._save_workflow(state, "execute_payment", paid)
        return paid

    def recover_payment(self, payment_id: str, account_id: str = "demo") -> dict:
        return self.authorize_draft(payment_id, account_id=account_id, recover=True)

    def authorize_draft(self, payment_id: str, step_up_confirmed: bool = False, account_id: str = "demo", *, recover: bool = False) -> dict:
        if self.payments is None:
            return {
                "success": False,
                "order_id": None,
                "charged": None,
                "currency": None,
                "payment_route": None,
                "ts": None,
                "error": "payment_offline",
                "payment_id": payment_id,
            }
        held = self._drafts.get(payment_id)
        if held and held.get("account_id") != account_id:
            return {"success": False, "order_id": None, "charged": None, "currency": "HKD",
                    "payment_route": None, "ts": None, "error": "payment_account_mismatch", "payment_id": payment_id}
        known = self.payments.get_payment(payment_id) if hasattr(self.payments, "get_payment") else None
        if known and known.get("account_id") and known["account_id"] != account_id:
            return {"success": False, "order_id": None, "charged": None, "currency": "HKD",
                    "payment_route": None, "ts": None, "error": "payment_account_mismatch", "payment_id": payment_id}
        if held and held.get("lines") and not held.get("captured_payment") and (known or {}).get("status") not in {"CAPTURED", "PENDING"}:
            profile = self._load_profile(account_id) or {}
            spent = profile.get("monthly_spent")
            if spent is None:
                spent = self._resolve_monthly_spent(account_id, 0)
            quote = held.get("quote") or {}
            policy, _ = self.policy.check_lines(
                held["lines"], float(quote.get("total_landed_cost") or (held.get("settlement") or {}).get("shelf_total") or 0),
                float(spent), **_policy_kwargs({"policy_caps": _caps_from(profile)}),
            )
            esc_id = held.get("approved_escalation")
            esc = self.policy.get_escalation(esc_id) if esc_id else None
            approved = bool(esc and esc.get("status") == "APPROVED" and
                            (not esc.get("account_id") or esc["account_id"] == account_id) and
                            _finite_money(esc.get("amount")) == _finite_money(policy.get("amount")))
            if policy.get("status") == "HALT" or (policy.get("status") == "ESCALATE" and not approved):
                return {"success": False, "order_id": None, "charged": None, "currency": "HKD",
                        "payment_route": None, "ts": None, "error": policy.get("reason") or "policy_changed",
                        "payment_id": payment_id}
        if recover:
            result = self.payments.recover(payment_id)
        else:
            result = self.payments.authorize(payment_id, step_up_confirmed=step_up_confirmed)
        if not result:
            return {
                "success": False,
                "order_id": None,
                "charged": None,
                "currency": None,
                "payment_route": None,
                "ts": None,
                "error": "Payment status is uncertain. Retry using the same draft to check or resume the payment.",
                "payment_id": payment_id,
                "retryable": True,
                "status": "PENDING",
            }
        ok = result.get("status") == "CAPTURED"
        shaped = {
            "success": ok,
            "order_id": result.get("order_id"),
            "charged": result.get("charged") if ok else None,
            "currency": result.get("currency") or "HKD",
            "payment_route": result.get("rail"),
            "ts": result.get("rail_ts") or result.get("updated_at"),
            "error": None if ok else (result.get("error") or result.get("detail") or "authorize_failed"),
            "payment_id": result.get("payment_id") or payment_id,
            "retryable": result.get("status") == "PENDING",
            "status": result.get("status"),
        }
        if ok:
            shaped["settlement_saved"] = self._save_paid(payment_id, shaped, account_id)
            shaped["settlement_pending"] = shaped["settlement_saved"] is False
        return shaped

    def _save_paid(self, payment_id: str, payment: dict, account_id: str) -> bool | None:
        """Write the captured basket to persistance as a paid order.

        Before, only the browser saved the order (after authorize). A capture
        made any other way (script, retry after a closed tab) never reached the
        order history. persistance dedups on payment_id, so the browser's own
        save afterwards is a no-op.
        """
        held = self._drafts.get(payment_id)
        if held is None:
            return None
        held = {**held, "captured_payment": payment}
        self._drafts[payment_id] = held
        if self.profile is None or not hasattr(self.profile, "settle"):
            return False
        settlement = dict(held.get("settlement") or {})
        settlement["payment_order_id"] = payment.get("order_id")
        lines = [
            {
                key: line.get(key)
                for key in ("sku", "name", "merchant", "category", "qty", "unit_price", "line_total")
            }
            for line in held.get("lines") or []
        ]
        merchants = [group.get("merchant") for group in settlement.get("merchants") or [] if group.get("merchant")]
        try:
            saved = self.profile.settle(
                held.get("account_id") or account_id,
                {
                    "amount": float(payment.get("charged") or settlement.get("total") or 0),
                    "currency": payment.get("currency") or "HKD",
                    "merchant": ", ".join(merchants),
                    "payment_route": payment.get("payment_route") or "",
                    "payment_id": payment_id,
                    "intent": held.get("intent") or "",
                    "lines": lines,
                    "settlement": settlement,
                    "benefits": settlement.get("benefits") or [],
                },
            )
        except Exception:
            return False
        if not isinstance(saved, dict) or not saved.get("order_id"):
            return False
        self._drafts.pop(payment_id, None)
        return True

    def recover_orders(self, account_id: str) -> dict:
        recovered = []
        pending = []
        for payment_id in list(self._drafts):
            held = self._drafts.get(payment_id) or {}
            if held.get("account_id") != account_id:
                continue
            if not held.get("captured_payment"):
                if payment_id.startswith("esc_") or self.payments is None or not hasattr(self.payments, "get_payment"):
                    continue
                record = self.payments.get_payment(payment_id)
                if not record or record.get("status") != "CAPTURED":
                    continue
                held["captured_payment"] = {
                    "success": True, "charged": record.get("charged"), "order_id": record.get("order_id"),
                    "currency": record.get("currency") or "HKD", "payment_route": record.get("rail"),
                    "payment_id": payment_id,
                }
            if self._save_paid(payment_id, held["captured_payment"], account_id):
                recovered.append(payment_id)
            else:
                pending.append(payment_id)
        return {"recovered": recovered, "pending": pending}

    def _escalate(self, state: AgentState) -> dict:
        product = state["product"]
        policy = state["policy"]
        caps = _policy_kwargs(state)
        record = self.policy.create_escalation(
            {
                "amount": state["quote"]["total_landed_cost"],
                "currency": "HKD",
                "merchant": product["merchant"],
                "category": product.get("category") or "",
                "sku": product["id"],
                "qty": state["goal"]["qty"],
                "reason": policy["reason"],
                "monthly_spent": float(state.get("monthly_spent") or 0),
                "account_id": state.get("account_id") or "",
                "run_id": state.get("run_id") or "",
                "order_id": state.get("order_id") or state.get("run_id") or "",
                "monthly_cap": caps.get("monthly_cap"),
                "per_transaction_cap": caps.get("per_transaction_cap"),
                "bulk_ceiling": caps.get("bulk_ceiling"),
                "product": product,
                "quote": state["quote"],
                "goal": state["goal"],
                "policy": policy,
                "intent": state["intent"],
            }
        )
        stored = self.policy.memory[record["escalation_id"]]
        self._drafts[record["escalation_id"]] = {
            "account_id": state.get("account_id") or "demo",
            "order_id": state.get("order_id") or state.get("run_id") or "",
            "intent": state.get("intent") or "",
            "lines": _review_lines(state), "quote": state["quote"],
            "settlement": state.get("settlement"), "product": product, "goal": state["goal"],
        }
        return {
            "path": ["create_escalation"],
            "plan_status": "ESCALATED",
            "escalation": stored,
            "escalation_id": record["escalation_id"],
            "pending_event": _pending("ESCALATION_CREATED", "PENDING", policy["reason"]),
        }

    def _ask(self, state: AgentState) -> dict:
        return {
            "path": ["ask"],
            "plan_status": "NEEDS_INPUT",
            "payment": None,
            "pending_event": _pending("FOLLOW_UP", "ASKED", state.get("question") or "Need a choice before paying."),
        }

    def _halt(self, state: AgentState) -> dict:
        policy = state["policy"]
        reason = policy["reason"]
        reply = state.get("reply") or ""
        if not reply and policy.get("rule") == "category_blacklisted":
            reply = _blacklist_only_reply(state)
        thought = reply or THOUGHTS["HALTED"]
        return {
            "path": ["halt"],
            "plan_status": "HALTED",
            "payment": None,
            "reply": reply,
            "pending_event": _pending("HALTED", "HALTED", reason, thought, policy_snapshot(policy)),
        }

    def _abort(self, state: AgentState) -> dict:
        status = state.get("escalation_status")
        if status == "EXPIRED":
            event = "ESCALATION_EXPIRED"
            reason = "TTL reached 0"
        elif status == "REFUSED":
            event = "ESCALATION_REFUSED"
            reason = "Mother refused"
        else:
            event = "HALTED"
            reason = "Unknown escalation"
        return {
            "path": ["abort"],
            "plan_status": "ABORTED",
            "pending_event": _pending(event, "ABORTED", reason),
        }

    def _hold(self, state: AgentState) -> dict:
        reason = (state.get("escalation") or {}).get("reason") or "Waiting for approval"
        return {
            "path": ["hold"],
            "plan_status": "ESCALATED",
            "pending_event": _pending("ESCALATION_CREATED", "PENDING", reason),
        }

    def _build(self):
        graph = StateGraph(AgentState)
        graph.add_node("route_entry", self._route_entry)
        graph.add_node("reason", self._reason)
        graph.add_node("plan", self._plan)
        graph.add_node("search_products", self._search)
        graph.add_node("price_cart", self._cart)
        graph.add_node("check_budget", self._budget)
        graph.add_node("execute_payment", self._pay)
        graph.add_node("preview", self._preview)
        graph.add_node("review", self._review)
        graph.add_node("user_limit", self._user_limit)
        graph.add_node("create_escalation", self._escalate)
        graph.add_node("halt", self._halt)
        graph.add_node("ask", self._ask)
        graph.add_node("abort", self._abort)
        graph.add_node("hold", self._hold)
        for name in (
            "audit_intent",
            "audit_plan",
            "audit_search",
            "audit_cart",
            "audit_policy",
            "audit_payment",
            "audit_escalation",
            "audit_halt",
            "audit_abort",
            "audit_hold",
            "audit_followup",
            "audit_preview",
            "audit_review",
        ):
            graph.add_node(name, self._audit(name))

        graph.add_edge(START, "route_entry")
        graph.add_conditional_edges(
            "route_entry",
            self._choose_entry,
            {
                "reason": "reason",
                "execute_payment": "execute_payment",
                "abort": "abort",
                "hold": "hold",
            },
        )
        graph.add_edge("reason", "audit_intent")
        graph.add_conditional_edges(
            "audit_intent",
            self._after_intent,
            {"plan": "plan", "end": END},
        )
        graph.add_edge("plan", "audit_plan")
        graph.add_edge("audit_plan", "search_products")
        graph.add_edge("search_products", "audit_search")
        graph.add_conditional_edges(
            "audit_search",
            self._after_search,
            {"price_cart": "price_cart", "end": END},
        )
        graph.add_edge("price_cart", "audit_cart")
        graph.add_conditional_edges(
            "audit_cart",
            self._after_cart,
            {"check_budget": "check_budget", "user_limit": "user_limit", "end": END},
        )
        graph.add_edge("check_budget", "audit_policy")
        graph.add_conditional_edges(
            "audit_policy",
            self._after_policy,
            {
                "execute_payment": "execute_payment",
                "create_escalation": "create_escalation",
                "halt": "halt",
                "ask": "ask",
                "preview": "preview",
                "review": "review",
                "end": END,
            },
        )
        graph.add_edge("review", "audit_review")
        graph.add_edge("audit_review", END)
        graph.add_edge("preview", "audit_preview")
        graph.add_edge("audit_preview", END)
        graph.add_edge("user_limit", END)
        graph.add_edge("ask", "audit_followup")
        graph.add_edge("audit_followup", END)
        graph.add_edge("execute_payment", "audit_payment")
        graph.add_edge("audit_payment", END)
        graph.add_edge("create_escalation", "audit_escalation")
        graph.add_edge("audit_escalation", END)
        graph.add_edge("halt", "audit_halt")
        graph.add_edge("audit_halt", END)
        graph.add_edge("abort", "audit_abort")
        graph.add_edge("audit_abort", END)
        graph.add_edge("hold", "audit_hold")
        graph.add_edge("audit_hold", END)
        return graph.compile()
