"""Live LangGraph for POST /agent/intent.

Same spine as graph/shopping_graph.py: reason, a fixed plan, tool calls,
then a policy branch. Each step is hashed into audit_log before the next
edge runs. Tool calls hit the mall and the policy service.
"""

from __future__ import annotations

import hashlib
import math
import operator
import os
import re
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from benefits import DEFAULT_RANK, connected_methods, explain_pick, settlement_for
from basket import (
    _blacklist_reply,
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
from models import ActionPlan
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
    r"under|within|budget(?: is| of)?|limit(?: is| of)?)\s*"
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
        "stock": int(raw.get("stock", 0)),
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
    """Thought, action, observation. The model's own steps come first, then each tool."""
    steps = []
    for item in llm_react or []:
        if isinstance(item, dict) and (item.get("thought") or item.get("observation")):
            steps.append(
                {
                    "thought": str(item.get("thought") or ""),
                    "action": str(item.get("action") or "reason"),
                    "observation": str(item.get("observation") or ""),
                    "source": "llm",
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
        "react": [],
        "audit_log": audit,
    }
    return ActionPlan.model_validate(plan).model_dump()


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
    def __init__(self, mall, policy: PolicyClient, planner=None, spend=None, profile=None, payments: PaymentClient | None = None):
        self.mall = mall
        self.policy = policy
        self.spend = spend
        self.profile = profile
        self.payments = payments
        self.planner = planner or OpenRouterPlanner()
        self.graph = self._build()

    def _catalog(self) -> list[dict]:
        products = getattr(self.mall, "products", None)
        if isinstance(products, list) and products:
            return products
        return self.mall.search("")

    def _resolve_monthly_spent(self, account_id: str, fallback: float) -> float:
        """Postgres spend is source of truth when persistance :8003 is up."""
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

    def run(
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
            "audit_log": result.get("audit_log", []),
        }
        plan = ActionPlan.model_validate(plan).model_dump()
        self._remember(account, result.get("order_id") or order_id, intent, plan)
        return plan

    def _audit(self, name: str):
        def audit(state: AgentState) -> dict:
            queued = state.get("policy_events") if name == "audit_policy" else None
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
        if record is None:
            return {
                "path": ["route_entry"],
                "escalation_status": "UNKNOWN",
            }
        update: dict = {
            "path": ["route_entry"],
            "escalation_status": record.get("status"),
            "escalation": record,
        }
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

    def _reason(self, state: AgentState) -> dict:
        catalog = self._catalog()
        covered = needs_for_every_category(state["intent"], catalog)
        if covered is None:
            covered = plan_fuzzy(state["intent"], catalog)
        if covered is not None and covered.get("question") and not covered.get("needs"):
            question = str(covered["question"])
            return {
                "path": ["reason"],
                "goal": goal_from(state["intent"], covered),
                "plan_status": "NEEDS_INPUT",
                "stop": True,
                "question": question,
                "reply": question,
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
        if needs and (wants_same_merchant(state["intent"]) or named_merchant(state["intent"])):
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
        if len(needs) >= 2 or merchant_reply:
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
            elif decision.get("model") == "catalog":
                named = "One item from each catalog category. Code fits the basket to policy."
            else:
                named = "Model may name each need. Code fits the basket to policy."
            return {
                "path": ["reason"],
                "goal": goal,
                "needs": needs,
                "reply": merchant_reply,
                "llm_react": llm_react,
                "pending_event": _pending("INTENT_RECEIVED", "PARSED", named, goal["thought"]),
            }
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
        return {
            "path": ["plan"],
            "pending_event": _pending(
                "PLAN",
                "FIXED_ORDER",
                "search_products, price_cart, check_budget, then the policy branch",
            ),
        }

    def _search(self, state: AgentState) -> dict:
        if state.get("needs"):
            count = len(state["needs"])
            return {
                "path": ["search_products"],
                "pending_event": _pending(
                    "SEARCH",
                    "RECORDED",
                    f"Basket of {count} needs.",
                    f"Shelf search kept {count} products.",
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
            return self.policy.check_lines(lines, amount, spent, **caps)

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
        try:
            requested = [{"sku": line["sku"], "qty": int(line["qty"])} for line in fitted["lines"]]
            _verify_cart_quote(fitted["quote"], requested, self._catalog())
        except ValueError as exc:
            return _failure("price_cart", "CART_PRICED", str(exc))
        first = fitted["lines"][0]
        fresh = self.mall.product(first["sku"])
        return {
            "path": ["price_cart"],
            "quote": _quote(fitted["quote"]),
            "product": _product(fresh),
            "lines": fitted["lines"],
            "repairs": fitted["repairs"],
            "question": fitted["question"],
            "reply": _join_reply(state.get("reply") or "", fitted.get("reply") or ""),
            "payment_route": fitted["payment_route"],
            "payment_reason": fitted["payment_reason"],
            "basket_policy": fitted["policy"],
            "policy_events": fitted["events"],
            "pending_event": _pending("CART_PRICED", "RECORDED", fitted["cart_reason"]),
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

    def confirm_basket(
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
        methods = connected_methods(profile.get("payment_methods"))
        rank = profile.get("benefit_rank") or DEFAULT_RANK
        removed = {sku for sku in (removed_skus or []) if sku}
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
        result, events = self.policy.check_lines(
            detailed,
            quote["total_landed_cost"],
            float(monthly_spent or 0),
            **_policy_kwargs({"policy_caps": _caps_from(profile)}),
        )
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
                audit=_policy_audit(result, events),
            )
        settlement = settlement_for(detailed, quote, methods, rank)
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
                    **caps,
                }
            )
        draft = None
        if result.get("status") == "PASS" and self.payments is not None:
            merchant = detailed[0].get("merchant") or ""
            held = self.payments.draft(
                amount=float(settlement["total"]),
                merchant=merchant,
                account_id=account,
                intent=intent,
                sku=detailed[0].get("sku") or "",
                qty=int(detailed[0].get("qty") or 1),
                rail=(settlement["merchants"][0]["payment"]["route"] if settlement["merchants"] else None),
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
        status = "ESCALATED" if result.get("status") == "ESCALATE" else "READY"
        return _plan_shell(
            intent,
            status,
            quote=quote,
            lines=detailed,
            policy=result,
            settlement=settlement,
            payment_draft=draft,
            escalation=escalation,
            reply=f"Rules checked again. Amount to approve is HK${float(settlement['total']):.2f}.",
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
        if self.payments is not None and payment_id:
            return self.authorize_draft(payment_id, step_up_confirmed=step_up_confirmed, account_id=account_id)
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
            draft = self.payments.draft(
                amount=authorized_total,
                merchant=merchant,
                account_id=state.get("account_id") or "demo",
                intent=str(state.get("intent") or ""),
                sku=str(sku or ""),
                qty=int(qty),
                rail=route,
            )
            if draft and draft.get("payment_id"):
                held = {
                    "path": ["execute_payment"],
                    "plan_status": "READY",
                    "payment": None,
                    "payment_route": route,
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

    def authorize_draft(self, payment_id: str, step_up_confirmed: bool = False, account_id: str = "demo") -> dict:
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
        result = self.payments.authorize(payment_id, step_up_confirmed=step_up_confirmed)
        if not result:
            return {
                "success": False,
                "order_id": None,
                "charged": None,
                "currency": None,
                "payment_route": None,
                "ts": None,
                "error": "authorize_failed",
                "payment_id": payment_id,
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
        }
        return shaped

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
