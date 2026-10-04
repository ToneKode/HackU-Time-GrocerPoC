"""LangGraph for the person 1 shopping agent.

The tool bodies are not implemented. Each step records the call, the rule,
and the arguments, then an audit node appends a hash-chained log entry.
The edge after audit_policy is the policy decision.

Regenerate the picture and the traces with:

    py -3.13 shopping_graph.py
"""

from __future__ import annotations

import hashlib
import json
import operator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

ROOT = Path(__file__).resolve().parent
RULES = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
GENESIS = RULES["audit"]["genesis_prev_hash"]
CLOCK = datetime.fromisoformat(RULES["clock_start"].replace("Z", "+00:00"))

# Topology. Conditional sources are route_entry and audit_policy.
EDGES: list[tuple[str, str, str]] = [
    ("__start__", "route_entry", ""),
    ("route_entry", "reason", "new intent"),
    ("route_entry", "execute_payment", "escalation APPROVED"),
    ("reason", "audit_intent", "log INTENT_RECEIVED"),
    ("audit_intent", "plan", "parsed"),
    ("plan", "audit_plan", "log PLAN"),
    ("audit_plan", "search_products", "fixed tool order"),
    ("search_products", "audit_search", "log SEARCH"),
    ("audit_search", "price_cart", "first product"),
    ("price_cart", "audit_cart", "log CART_PRICED"),
    ("audit_cart", "check_budget", "amount = total_landed_cost"),
    ("check_budget", "audit_policy", "log POLICY_CHECK"),
    ("audit_policy", "execute_payment", "PASS at or under 500"),
    ("audit_policy", "create_escalation", "ESCALATE 500 to 800"),
    ("audit_policy", "halt", "HALT"),
    ("execute_payment", "audit_payment", "log PAYMENT"),
    ("audit_payment", "__end__", "plan closes"),
    ("create_escalation", "audit_escalation", "log ESCALATION_CREATED"),
    ("audit_escalation", "__end__", "ESCALATED, request returns"),
    ("halt", "audit_halt", "log HALTED"),
    ("audit_halt", "__end__", "do not pay"),
]

CONDITIONAL = {"route_entry", "audit_policy"}
AUDIT_NODES = {
    "audit_intent",
    "audit_plan",
    "audit_search",
    "audit_cart",
    "audit_policy",
    "audit_payment",
    "audit_escalation",
    "audit_halt",
}


class AgentState(TypedDict, total=False):
    intent: str
    scenario: str
    monthly_spent: float
    escalation_id: str
    escalation_status: str
    goal: dict
    policy_status: str
    policy_reason: str
    pending_event: dict
    path: Annotated[list, operator.add]
    audit_log: Annotated[list, operator.add]


def _scenario(state: AgentState) -> dict:
    return RULES["scenarios"][state["scenario"]]


def _checks(fired: str) -> list[dict]:
    rows = []
    for name in RULES["policy_check_order"]:
        if name == fired:
            rows.append({"check": name, "result": "fired"})
            break
        rows.append({"check": name, "result": "clear"})
    return rows


def _action_input(name: str, state: AgentState, scenario: dict) -> dict:
    if name == "reason":
        return {"intent": state["intent"]}
    if name == "plan":
        return {"tool_order": RULES["tool_order"]}
    if name == "search_products":
        return {"q": scenario["query"]}
    if name == "price_cart":
        return {"items": [{"sku": scenario["sku"], "qty": scenario["qty"]}]}
    if name == "check_budget":
        return {
            "merchant": scenario["merchant"],
            "category": scenario["category"],
            "amount": scenario["total_landed_cost"],
            "currency": "HKD",
            "sku": scenario["sku"],
            "qty": scenario["qty"],
            "monthly_spent": scenario["monthly_spent"],
        }
    if name == "execute_payment":
        return {
            "cart_total": scenario["total_landed_cost"],
            "payment_route": RULES["default_payment_route"],
            "idempotency_key": scenario["idempotency_key"],
        }
    if name == "create_escalation":
        return {
            "amount": scenario["total_landed_cost"],
            "currency": "HKD",
            "merchant": scenario["merchant"],
            "sku": scenario["sku"],
            "qty": scenario["qty"],
            "reason": scenario["policy_reason"],
            "ttl_seconds": RULES["escalation_ttl_seconds"],
        }
    if name == "halt":
        return {"policy_status": scenario["policy_status"]}
    return {}


def _stamp(log: list, pending: dict) -> dict:
    index = len(log)
    prev = log[-1]["hash"] if log else GENESIS
    ts = (CLOCK + timedelta(seconds=index)).strftime("%Y-%m-%dT%H:%M:%SZ")
    event = pending["event"]
    status = pending["status"]
    reason = pending["reason"]
    material = RULES["audit"]["hash_join"].join(
        [str(index), ts, event, status, reason, prev]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    entry = {
        "index": index,
        "ts": ts,
        "event": event,
        "status": status,
        "reason": reason,
        "prev_hash": prev,
        "hash": digest,
        "node": pending["node"],
        "stage": pending["stage"],
        "thought": pending["thought"],
        "call": pending["call"],
        "action_input": pending["action_input"],
        "rule": pending["rule"],
        "tool_called": pending["tool_called"],
    }
    for extra in ("checks", "fired_check", "guard", "goal", "ttl_seconds"):
        if extra in pending:
            entry[extra] = pending[extra]
    return entry


def route_entry(state: AgentState) -> dict:
    return {"path": ["route_entry"]}


def choose_entry(state: AgentState) -> str:
    if state.get("escalation_status") == "APPROVED" and state.get("escalation_id"):
        return "execute_payment"
    return "reason"


def choose_policy_edge(state: AgentState) -> str:
    status = state.get("policy_status")
    return {
        "PASS": "execute_payment",
        "ESCALATE": "create_escalation",
        "HALT": "halt",
    }[status]


def make_step(name: str):
    spec = RULES["nodes"][name]

    def step(state: AgentState) -> dict:
        scenario = _scenario(state)
        status = spec.get("log_status", "")
        reason = spec.get("reason", "")
        if spec.get("log_status_from_scenario"):
            status = scenario["policy_status"]
        if spec.get("reason_from_scenario"):
            reason = scenario["policy_reason"]
        pending = {
            "node": name,
            "stage": spec["stage"],
            "thought": spec["thought"],
            "event": spec["event"],
            "status": status,
            "reason": reason,
            "call": spec["call"],
            "action_input": _action_input(name, state, scenario),
            "rule": spec["rule"],
            "tool_called": False,
        }
        update: dict = {"path": [name], "pending_event": pending}
        if spec.get("sets_goal_from_scenario"):
            goal = {
                "intent": state["intent"],
                "query": scenario["query"],
                "qty": scenario["qty"],
            }
            pending["goal"] = goal
            update["goal"] = goal
        if spec.get("sets_policy_from_scenario"):
            pending["checks"] = _checks(scenario["fired_check"])
            pending["fired_check"] = scenario["fired_check"]
            update["policy_status"] = scenario["policy_status"]
            update["policy_reason"] = scenario["policy_reason"]
        if spec.get("pay_guard"):
            if state.get("policy_status") == "PASS":
                pending["guard"] = "passed because policy status is PASS"
            elif (
                state.get("escalation_status") == "APPROVED"
                and state.get("escalation_id")
            ):
                pending["guard"] = "passed because escalation status is APPROVED"
            else:
                pending["status"] = "BLOCKED"
                pending["guard"] = "blocked"
                pending["reason"] = "Pay allowed only after PASS or APPROVED"
        if name == "create_escalation":
            pending["ttl_seconds"] = RULES["escalation_ttl_seconds"]
        return update

    step.__name__ = name
    return step


def make_audit(name: str):
    def audit(state: AgentState) -> dict:
        entry = _stamp(state.get("audit_log", []), state["pending_event"])
        return {"path": [name], "audit_log": [entry]}

    audit.__name__ = name
    return audit


def build():
    graph = StateGraph(AgentState)
    graph.add_node("route_entry", route_entry)
    for name in RULES["nodes"]:
        graph.add_node(name, make_step(name))
    for name in AUDIT_NODES:
        graph.add_node(name, make_audit(name))

    grouped: dict[str, list[str]] = {}
    for src, dst, _label in EDGES:
        grouped.setdefault(src, []).append(dst)

    for src, dests in grouped.items():
        if src == "__start__":
            graph.add_edge(START, dests[0])
            continue
        mapped = [END if dst == "__end__" else dst for dst in dests]
        if src in CONDITIONAL:
            router = choose_entry if src == "route_entry" else choose_policy_edge
            graph.add_conditional_edges(src, router, {dst: dst for dst in mapped})
        else:
            graph.add_edge(src, mapped[0])
    return graph.compile()


def _node_id(name: str) -> str:
    return {"__start__": "start", "__end__": "finish"}.get(name, name)


def to_mermaid() -> str:
    lines = ["flowchart TD"]
    lines.append("  start([Mother sends an intent])")
    lines.append("  finish([ActionPlan])")
    for src, dst, label in EDGES:
        left = _node_id(src)
        right = _node_id(dst)
        if label:
            lines.append(f"  {left} -->|{label}| {right}")
        else:
            lines.append(f"  {left} --> {right}")
    lines.append("  classDef audit fill:#143d66,stroke:#8ecae6,color:#f8f9fa")
    lines.append("  classDef step fill:#1b4332,stroke:#95d5b2,color:#f8f9fa")
    lines.append("  classDef gate fill:#9b2226,stroke:#ffb4a2,color:#ffffff")
    lines.append(
        "  class audit_intent,audit_plan,audit_search,audit_cart,audit_payment,audit_escalation,audit_halt audit"
    )
    lines.append(
        "  class reason,plan,search_products,price_cart,check_budget,execute_payment,create_escalation,halt step"
    )
    lines.append("  class route_entry,audit_policy gate")
    return "\n".join(lines) + "\n"


def _compiled_pairs(compiled) -> set[tuple[str, str]]:
    pairs = set()
    for edge in compiled.get_graph().edges:
        pairs.add((edge.source, edge.target))
    return pairs


def walk(compiled, scenario_name: str) -> dict:
    scenario = RULES["scenarios"][scenario_name]
    state = {
        "intent": scenario["intent"],
        "scenario": scenario_name,
        "monthly_spent": scenario.get("monthly_spent", 0),
        "path": [],
        "audit_log": [],
    }
    if scenario.get("escalation_id"):
        state["escalation_id"] = scenario["escalation_id"]
        state["escalation_status"] = scenario["escalation_status"]
    result = compiled.invoke(state)
    path = result["path"]
    if path != scenario["expected_path"]:
        raise SystemExit(f"{scenario_name} path {path} != {scenario['expected_path']}")
    return {
        "scenario": scenario_name,
        "intent": scenario["intent"],
        "tools_implemented": False,
        "expected_plan_status": scenario["expected_plan_status"],
        "path": path,
        "audit_log": result["audit_log"],
    }


def _html(mermaid: str, traces: list[dict]) -> str:
    sections = []
    for trace in traces:
        rows = []
        for entry in trace["audit_log"]:
            rows.append(
                "<tr>"
                f"<td>{entry['index']}</td>"
                f"<td>{entry['event']}</td>"
                f"<td>{entry['status']}</td>"
                f"<td>{entry['reason']}</td>"
                f"<td><code>{entry['hash'][:12]}</code></td>"
                f"<td>{'yes' if entry['tool_called'] else 'no'}</td>"
                "</tr>"
            )
        crumb = " → ".join(trace["path"])
        sections.append(
            f"<h2>{trace['scenario']}</h2>"
            f"<p>Expected plan status once the tools exist: <strong>{trace['expected_plan_status']}</strong></p>"
            f"<p class=\"path\">{crumb}</p>"
            "<table><thead><tr><th>#</th><th>Event</th><th>Status</th><th>Reason</th><th>Hash</th><th>Tool called</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopping agent LangGraph</title>
  <script type="module">
    import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
    mermaid.initialize({{ startOnLoad: true, flowchart: {{ htmlLabels: true, curve: "basis" }} }});
  </script>
  <style>
    body {{ margin: 0; font-family: Georgia, serif; background: #f4f1ea; color: #1c1915; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1 {{ font-weight: 600; letter-spacing: -0.03em; margin-bottom: 0; }}
    .lede {{ max-width: 46rem; line-height: 1.45; }}
    .mermaid {{ background: white; border: 1px solid #d9d3c7; padding: 12px; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; background: white; font-family: Consolas, monospace; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e4ddd0; text-align: left; padding: 8px; vertical-align: top; }}
    th {{ font-family: Georgia, serif; }}
    .path {{ font-family: Consolas, monospace; font-size: 13px; line-height: 1.5; }}
    .swatch {{ display: inline-block; width: 0.8em; height: 0.8em; margin-right: 0.3em; vertical-align: -0.05em; }}
  </style>
</head>
<body>
<main>
  <h1>Shopping agent LangGraph</h1>
  <p class="lede">Person 1. Reason, then a fixed plan, then the tool calls. The blue nodes are the log. A log entry is hashed before the next edge runs. Tool bodies are not implemented, so every row says the tool was not called. The branch labels are the rules.</p>
  <p>
    <span class="swatch" style="background:#1b4332"></span>step
    <span class="swatch" style="background:#143d66"></span>audit log
    <span class="swatch" style="background:#9b2226"></span>branch
  </p>
  <pre class="mermaid">{mermaid}</pre>
  {''.join(sections)}
</main>
</body>
</html>
"""


def main() -> None:
    compiled = build()
    expected = {(src, dst) for src, dst, _label in EDGES}
    actual = _compiled_pairs(compiled)
    if actual != expected:
        raise SystemExit(f"compiled edges differ\\nmissing {expected - actual}\\nextra {actual - expected}")

    mermaid = to_mermaid()
    (ROOT / "shopping_graph.mmd").write_text(mermaid, encoding="utf-8")
    (ROOT / "shopping_graph.langgraph.mmd").write_text(
        compiled.get_graph().draw_mermaid(), encoding="utf-8"
    )
    (ROOT / "shopping_graph.txt").write_text(
        compiled.get_graph().draw_ascii(), encoding="utf-8"
    )

    trace_dir = ROOT / "traces"
    trace_dir.mkdir(exist_ok=True)
    traces = []
    for name in RULES["scenarios"]:
        trace = walk(compiled, name)
        traces.append(trace)
        (trace_dir / f"{name}.json").write_text(
            json.dumps(trace, indent=2) + "\n", encoding="utf-8"
        )
    (ROOT / "preview.html").write_text(_html(mermaid, traces), encoding="utf-8")
    print(f"wrote {len(traces)} traces and preview.html")


if __name__ == "__main__":
    main()
