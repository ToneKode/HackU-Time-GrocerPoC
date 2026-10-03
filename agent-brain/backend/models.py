from typing import Literal

from pydantic import BaseModel, Field

PlanStatus = Literal[
    "READY",
    "COMPLETED",
    "HALTED",
    "ESCALATED",
    "ABORTED",
    "FAILED",
    "NEEDS_INPUT",
]
PolicyStatus = Literal["PASS", "ESCALATE", "HALT", "SKIPPED"]
EscalationStatus = Literal["PENDING", "APPROVED", "REFUSED", "EXPIRED"]


class IntentIn(BaseModel):
    intent: str = Field(min_length=1)
    monthly_spent: float = 0
    escalation_id: str | None = None
    account_id: str | None = None
    # preview=True: stop after pricing and return READY with a preview_id (no policy check, no payment).
    # preview_id: confirm that basket; the agent continues with the policy check and payment.
    preview: bool = False
    preview_id: str | None = None


class Goal(BaseModel):
    intent: str
    query: str
    qty: int
    sell_point: str = ""
    sku: str = ""
    thought: str = ""
    model: str = ""


class Product(BaseModel):
    id: str
    name: str
    price: float
    currency: str
    merchant: str
    category: str
    stock: int
    image_url: str = ""
    sell_point: str = ""


class CartLine(BaseModel):
    sku: str
    name: str
    merchant: str
    category: str
    unit_price: float
    qty: int
    line_total: float


class CartQuote(BaseModel):
    line_items: list[CartLine]
    subtotal: float
    shipping_fee: float
    tax: float
    total_landed_cost: float
    currency: str
    free_shipping_threshold: float


class PolicyResult(BaseModel):
    status: PolicyStatus
    reason: str
    amount: float
    currency: str
    monthly_spent: float
    monthly_remaining: float
    per_transaction_cap: int
    monthly_cap: int
    bulk_ceiling: int
    rule: str = ""


class PayResult(BaseModel):
    success: bool
    order_id: str | None
    charged: float | None
    currency: str | None
    payment_route: str | None
    ts: str | None
    error: str | None


class Escalation(BaseModel):
    escalation_id: str
    status: EscalationStatus
    ttl_seconds: int
    expires_at: str
    remaining_seconds: int
    amount: float
    currency: str
    merchant: str
    sku: str
    reason: str


class BasketLine(BaseModel):
    need: str
    priority: int
    sku: str
    name: str
    merchant: str
    category: str
    sell_point: str = ""
    qty: int
    unit_price: float
    line_total: float
    product_reason: str
    merchant_reason: str


class BasketRepair(BaseModel):
    need: str
    from_sku: str
    to_sku: str
    saved: float
    reason: str


class ReactStep(BaseModel):
    thought: str = ""
    action: str = ""
    observation: str = ""
    source: str = ""


class AuditEntry(BaseModel):
    index: int
    ts: str
    event: str
    status: str
    reason: str
    thought: str
    result: dict | None = None
    prev_hash: str
    hash: str


class ActionPlan(BaseModel):
    intent: str
    status: PlanStatus
    goal: Goal | None = None
    product: Product | None = None
    quote: CartQuote | None = None
    policy: PolicyResult | None = None
    escalation: Escalation | None = None
    payment: PayResult | None = None
    lines: list[BasketLine] = Field(default_factory=list)
    repairs: list[BasketRepair] = Field(default_factory=list)
    payment_route: str = ""
    payment_reason: str = ""
    question: str = ""
    reply: str = ""
    react: list[ReactStep] = Field(default_factory=list)
    audit_log: list[AuditEntry]
    preview_id: str = ""
