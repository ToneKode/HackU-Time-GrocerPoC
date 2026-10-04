"""Person 1 HTTP server.

GET / points at the shop. POST /agent/intent runs the LangGraph.
The reason node calls OpenRouter. The mall is fake_mall/*.json until
MOCK_API_BASE_URL is set. Policy calls go to port 8001 and fall back to the same caps.
Monthly spend is read/written on persistance :8003 when that API is up.

    py -3.13 server.py
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import httpx

from agent_graph import ShoppingAgent
from clients import MallClient, PaymentClient, PolicyClient, ProfileClient, SpendClient
from fake_mall import FileMall
from models import ActionPlan, IntentIn, PayResult

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
HOME = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Time Grocer agent</title></head>
<body>
  <p>The shop is at <a href="http://localhost:5173/agent">http://localhost:5173/agent</a>.</p>
  <p>This port accepts POST /agent/intent. The shop draws the reply. The plan is not printed here.</p>
</body>
</html>
"""


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(Path(__file__).resolve().parent / ".env")


class ConfirmPaymentIn(BaseModel):
    payment_id: str = Field(min_length=1)
    step_up_confirmed: bool = False
    account_id: str | None = None


class BasketLineIn(BaseModel):
    sku: str = Field(min_length=1)
    qty: int = 1


class ConfirmBasketIn(BaseModel):
    intent: str = ""
    account_id: str | None = None
    monthly_spent: float = 0
    lines: list[BasketLineIn]
    removed_skus: list[str] = Field(default_factory=list)


class AlternativesIn(BaseModel):
    intent: str = ""
    sku: str = Field(min_length=1)
    exclude_skus: list[str] = Field(default_factory=list)


class ApproveBasketIn(BaseModel):
    amount: float
    payment_id: str | None = None
    step_up_confirmed: bool = False
    account_id: str | None = None
    payment_route: str = "mastercard"
    merchant: str = ""


def products_from_persistance(base: str) -> list[dict]:
    """Full shelf for pricing. The planner still receives a short list."""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                base.rstrip("/") + "/catalog/products",
                params={"limit": 6000},
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError, OSError):
        return []
    if not isinstance(body, list) or not body or not isinstance(body[0], dict):
        return []
    if "id" not in body[0] or "price" not in body[0]:
        return []
    return [_normalize_row(row) for row in body]


FULL_CATALOG = Path(__file__).resolve().parent.parent / "hk_products_full.json"


def _normalize_row(row: dict) -> dict:
    """Keep unknown stock distinct from a known zero for allocation tools."""
    return dict(row)


def products_from_file(path: Path = FULL_CATALOG) -> list[dict]:
    """The real 5k-row HK catalog, used when persistance :8003 is down.

    Before this, the agent fell back to the 30-row fake_mall shelf, so meal
    plans were built from a handful of demo products.
    """
    if os.environ.get("AGENT_CATALOG", "").strip().lower() == "fake":
        return []
    try:
        import json

        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    return [_normalize_row(row) for row in rows if isinstance(row, dict) and "id" in row and "price" in row]


def _scripted_planner(intent: str, catalog: list[dict]) -> dict:
    """Offline planner for demos when OpenRouter is unavailable (USE_SCRIPTED_PLANNER=true)."""
    text = intent.casefold()
    qty = 1
    if "2 " in text or text.startswith("2"):
        qty = 2
    if "toilet" in text:
        sell = "best_rating" if "best" in text else "highest_usage" if "everyday" in text else "cheap"
        sku = {"cheap": "SKU001", "highest_usage": "SKU002", "best_rating": "SKU003"}[sell]
        return {
            "query": "toilet paper",
            "qty": qty,
            "sell_point": sell,
            "sku": sku,
            "thought": f"Toilet paper, {sell}.",
            "model": "scripted",
        }
    if "rice" in text:
        return {
            "query": "rice",
            "qty": 1,
            "sell_point": "cheap",
            "sku": "SKU004",
            "thought": "Cheap rice.",
            "model": "scripted",
        }
    return {
        "query": text.strip() or intent,
        "qty": qty,
        "sell_point": "cheap",
        "sku": "",
        "thought": "Scripted planner: pick the cheapest match.",
        "model": "scripted",
    }


def create_app(agent: ShoppingAgent | None = None) -> FastAPI:
    app = FastAPI(title="Person 1 agent")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN, "http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["*"],
    )
    if agent is None:
        mall_url = os.environ.get("MOCK_API_BASE_URL", "").strip()
        if mall_url:
            mall = MallClient(mall_url)
        else:
            rows = products_from_persistance(
                os.environ.get("PERSISTANCE_API_BASE_URL", "http://localhost:8003")
            )
            if not rows:
                rows = products_from_file()
            mall = FileMall(products=rows) if rows else FileMall()
        planner = None
        if os.environ.get("USE_SCRIPTED_PLANNER", "").lower() in {"1", "true", "yes"}:
            planner = _scripted_planner
        persistance = os.environ.get("PERSISTANCE_API_BASE_URL", "http://localhost:8003")
        agent = ShoppingAgent(
            mall,
            PolicyClient(os.environ.get("POLICY_API_BASE_URL", "http://localhost:8001")),
            planner=planner,
            spend=SpendClient(persistance, account_id=os.environ.get("ACCOUNT_ID", "demo")),
            profile=ProfileClient(persistance),
            payments=PaymentClient(os.environ.get("PAYMENT_API_BASE_URL", "http://localhost:8004")),
        )
    shopping = agent

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return HOME

    @app.post("/agent/intent", response_model=ActionPlan)
    def agent_intent(body: IntentIn) -> ActionPlan:
        plan = shopping.run(
            body.intent,
            body.monthly_spent,
            body.escalation_id,
            account_id=body.account_id,
        )
        return ActionPlan.model_validate(plan)

    @app.post("/agent/payment/authorize", response_model=PayResult)
    def agent_authorize(body: ConfirmPaymentIn) -> PayResult:
        account = (body.account_id or os.environ.get("ACCOUNT_ID") or "demo").strip() or "demo"
        result = shopping.authorize_draft(
            body.payment_id,
            step_up_confirmed=body.step_up_confirmed,
            account_id=account,
        )
        return PayResult.model_validate(result)

    @app.post("/agent/basket/optimize")
    def optimize_basket(body: ConfirmBasketIn) -> dict:
        try:
            return shopping.tools["optimize_basket"](
                body.intent, [line.model_dump() for line in body.lines], account_id=body.account_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/agent/payment/recover", response_model=PayResult)
    def agent_recover(body: ConfirmPaymentIn) -> PayResult:
        account = (body.account_id or os.environ.get("ACCOUNT_ID") or "demo").strip() or "demo"
        return PayResult.model_validate(shopping.recover_payment(body.payment_id, account_id=account))

    @app.post("/agent/orders/recover")
    def recover_orders(account_id: str = "demo") -> dict:
        return shopping.recover_orders(account_id)

    @app.post("/agent/basket/confirm", response_model=ActionPlan)
    def basket_confirm(body: ConfirmBasketIn) -> ActionPlan:
        plan = shopping.confirm_basket(
            body.intent,
            [line.model_dump() for line in body.lines],
            body.removed_skus,
            monthly_spent=body.monthly_spent,
            account_id=body.account_id,
        )
        return ActionPlan.model_validate(plan)

    @app.post("/agent/basket/alternatives")
    def basket_alternatives(body: AlternativesIn) -> dict:
        """Swap options for one basket line, from the real catalog (same food group)."""
        return {
            "sku": body.sku,
            "alternatives": shopping.basket_alternatives(body.intent, body.sku, body.exclude_skus),
        }

    @app.post("/agent/basket/approve", response_model=PayResult)
    def basket_approve(body: ApproveBasketIn) -> PayResult:
        account = (body.account_id or os.environ.get("ACCOUNT_ID") or "demo").strip() or "demo"
        result = shopping.approve_payment(
            amount=body.amount,
            payment_id=body.payment_id,
            step_up_confirmed=body.step_up_confirmed,
            account_id=account,
            payment_route=body.payment_route,
            merchant=body.merchant,
        )
        return PayResult.model_validate(result)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("AGENT_HOST", "0.0.0.0"),
        port=int(os.environ.get("AGENT_PORT", "8002")),
    )
