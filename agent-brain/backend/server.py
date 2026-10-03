"""Person 1 HTTP server.

GET / is the chat page. POST /agent/intent runs the LangGraph.
The reason node calls OpenRouter. The mall is fake_mall/*.json until
MOCK_API_BASE_URL is set. Policy calls go to port 8001 and fall back to the same caps.

    py -3.13 server.py
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from agent_graph import ShoppingAgent
from clients import MallClient, PolicyClient
from fake_mall import FileMall
from models import ActionPlan, IntentIn

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
PAGE = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


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


def create_app(agent: ShoppingAgent | None = None) -> FastAPI:
    app = FastAPI(title="Person 1 agent")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN, "http://127.0.0.1:5173"],
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["*"],
    )
    if agent is None:
        mall_url = os.environ.get("MOCK_API_BASE_URL", "").strip()
        mall = MallClient(mall_url) if mall_url else FileMall()
        agent = ShoppingAgent(
            mall,
            PolicyClient(os.environ.get("POLICY_API_BASE_URL", "http://localhost:8001")),
        )
    shopping = agent

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.post("/agent/intent", response_model=ActionPlan)
    def agent_intent(body: IntentIn) -> ActionPlan:
        plan = shopping.run(body.intent, body.monthly_spent, body.escalation_id)
        return ActionPlan.model_validate(plan)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("AGENT_HOST", "0.0.0.0"),
        port=int(os.environ.get("AGENT_PORT", "8002")),
    )
