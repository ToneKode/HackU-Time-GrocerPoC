"""Simulated model conversations exercise tool sequencing and trusted evidence."""

from copy import deepcopy
import json

import pytest

from openrouter import PlannerError
from tool_planner import TOOL_SCHEMAS, ToolPlanner, ToolPlannerError

INTENT = "Choose snacks for my family"
A = {"sku": "snack-a", "qty": 1}
B = {"sku": "snack-b", "qty": 2}


def call(name, args, call_id=None):
    return {"id": call_id or name, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def reply(*calls, content="Check the catalog and compare this basket."):
    return {"role": "assistant", "content": content, "tool_calls": list(calls)}


def search(**filters):
    return call("search_catalog", filters)


def optimize(lines, intent=INTENT):
    return call("optimize_basket", {"intent": intent, "lines": lines})


def finish(lines, summary="These snacks fit the family request."):
    return call("finish_plan", {"lines": lines, "summary": summary})


class ScriptedChat:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, messages, tools):
        self.requests.append(deepcopy(messages))
        assert {tool["function"]["name"] for tool in tools} == {
            "search_catalog", "optimize_basket", "finish_plan",
        }
        response = self.responses.pop(0)
        return response(messages) if callable(response) else response


def test_batch_search_reduces_three_targets_to_one_call_and_audits_each():
    def catalog(**filters):
        if filters['q'] == 'unavailable': raise ValueError('Merchant feed unavailable')
        row = {'id': A['sku'] if filters['offset'] == 0 else B['sku'], 'name': 'Snack'}
        return {'products': [row], 'total_count': 305, 'has_more': True}
    chat = ScriptedChat(reply(search(targets=[{'q': 'rice'}, {'q': 'nuts', 'offset': 1}, {'q': 'unavailable'}])),
                        reply(optimize([A, B])), reply(finish([A, B])))
    result = ToolPlanner(chat, catalog, Optimizer(), max_tool_calls=3)(INTENT)
    targets = [e for e in result['decision_events'] if e['action'] == 'search_catalog_target']
    assert len(targets) == 3 and targets[-1]['status'] == 'error'
    assert targets[0]['result']['total_count'] == 305
    evidence = json.loads(chat.requests[1][-1]['content'])
    assert len(evidence['results']) == 3
    assert result['needs'][1]['sku'] == B['sku']


def test_multi_category_search_leaves_turns_for_optimization_and_finish():
    chat = ScriptedChat(*[reply(search(category='Snacks', limit=1)) for _ in range(8)],
                        reply(optimize([A])), reply(finish([A])))
    result = ToolPlanner(chat, Catalog(), Optimizer(), max_rounds=16)(INTENT)
    assert result['needs'][0]['sku'] == A['sku']
    assert len(chat.requests) == 10
    assert 'optimize a candidate basket now' in chat.requests[5][0]['content']
    assert 'literal phrase substring' in chat.requests[0][0]['content']
    assert result['decision_events'][-1]['action'] == 'finish_plan'


class Catalog:
    def __init__(self):
        self.requests = []

    def __call__(self, **filters):
        self.requests.append(filters)
        offset = filters["offset"]
        if offset == 0:
            rows = [{"id": A["sku"], "name": "Oat crackers", "category": "Snacks"}]
        elif offset == 1:
            rows = [{"id": B["sku"], "name": "Nut mix", "category": "Snacks"}]
        else:
            rows = []
        return {"products": rows, "total_count": 305, "has_more": offset + len(rows) < 305}


class Optimizer:
    def __init__(self):
        self.requests = []

    def __call__(self, *, intent, lines):
        self.requests.append({"intent": intent, "lines": deepcopy(lines)})
        return {"lines": deepcopy(lines), "optimization": {"feasible": True}}


def tool_events(events):
    return [event for event in events if "tool_call_id" in event]


def assert_error(event, text):
    assert event["status"] == "error"
    assert text in event["result"]["error"]["message"]


def test_model_directs_filters_pagination_and_audited_final_basket():
    def next_page(messages):
        evidence = json.loads(messages[-1]["content"])
        assert evidence["total_count"] == 305
        assert evidence["has_more"] is True
        return reply(search(category="Snacks", merchant="PARKnSHOP", limit=1, offset=1))

    chat = ScriptedChat(
        reply(search(category="Snacks", merchant="PARKnSHOP", limit=1)), next_page,
        reply(optimize([A, B])),
        reply(finish([{**A, "reason": "A family snack", "priority": 2},
                      {**B, "query": "nuts", "priority": 1}])),
    )
    catalog, optimizer = Catalog(), Optimizer()
    result = ToolPlanner(chat, catalog, optimizer, model="simulated")(INTENT, [{"id": "ignored"}])
    assert catalog.requests == [
        {"q": "", "category": "Snacks", "merchant": "PARKnSHOP", "limit": 1, "offset": 0},
        {"q": "", "category": "Snacks", "merchant": "PARKnSHOP", "limit": 1, "offset": 1},
    ]
    assert optimizer.requests == [{"intent": INTENT, "lines": [A, B]}]
    assert result["query"] == "Oat crackers"
    assert result["qty"] == 1 and result["sku"] == A["sku"]
    assert result["model"] == "simulated"
    assert result["needs"] == [
        {"query": "Oat crackers", **A, "priority": 2, "reason": "A family snack"},
        {"query": "nuts", **B, "priority": 1, "reason": result["thought"]},
    ]
    events = result["decision_events"]
    assert result["react"] == events
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert len([event for event in events if event["action"] == "model_decision"]) == 4
    for event in events:
        assert {"thought", "action", "args", "observation", "result"} <= event.keys()
        assert json.loads(event["observation"]) == event["result"]
    tools = tool_events(events)
    assert [event["action"] for event in tools] == ["search_catalog", "search_catalog", "optimize_basket", "finish_plan"]
    assert tools[0]["args"]["category"] == "Snacks"
    assert tools[0]["result"]["total_count"] == 305
    assert tools[-1]["result"]["accepted"] is True


def test_revised_quantities_force_new_optimization():
    revised = {**A, "qty": 3}
    chat = ScriptedChat(reply(search()), reply(optimize([A])), reply(finish([revised])),
                        reply(optimize([revised])), reply(finish([revised])))
    optimizer = Optimizer()
    result = ToolPlanner(chat, Catalog(), optimizer)(INTENT)
    assert [request["lines"] for request in optimizer.requests] == [[A], [revised]]
    assert_error(tool_events(result["decision_events"])[2], "exact final lines")
    assert result["needs"][0]["qty"] == 3
    assert "error" in json.loads(chat.requests[3][-1]["content"])


def test_optimizer_swap_requires_search_and_optimization_of_final_selected_sku():
    swapped = {"sku": B["sku"], "qty": 1}
    requests = []

    def swap_optimizer(**kwargs):
        requests.append(deepcopy(kwargs))
        return {"lines": [{**swapped, "merchant": "PARKnSHOP", "unit_price": 10}]}

    chat = ScriptedChat(reply(search()), reply(optimize([A])), reply(finish([swapped])),
                        reply(search(offset=1)), reply(finish([swapped])),
                        reply(optimize([swapped])), reply(finish([swapped])))
    result = ToolPlanner(chat, Catalog(), swap_optimizer, max_rounds=8)(INTENT)
    tools = tool_events(result["decision_events"])
    assert_error(tools[2], "not been seen")
    assert_error(tools[4], "exact final lines")
    assert requests == [{"intent": INTENT, "lines": [A]}, {"intent": INTENT, "lines": [swapped]}]
    assert result["needs"][0]["sku"] == B["sku"]


def test_same_round_tools_execute_in_order_and_reordered_final_lines_are_equivalent():
    chat = ScriptedChat(reply(search(), search(offset=1), optimize([A, B]), finish([B, A])))
    result = ToolPlanner(chat, Catalog(), Optimizer())(INTENT)
    assert len(tool_events(result["decision_events"])) == 4
    assert result["needs"][0]["sku"] == B["sku"]


@pytest.mark.parametrize("responses, expected", [
    ([reply(finish([A]))], "successful catalog search"),
    ([reply(search()), reply(finish([A]))], "exact final lines"),
    ([reply(search()), reply(optimize([A])), reply(finish([{**A, "sku": "invented"}]))], "not been seen"),
    ([reply(search()), reply(search(offset=1)), reply(optimize([A])), reply(finish([B]))], "exact final lines"),
    ([reply(search()), reply(optimize([A])), reply(finish([A], "Only one snack is available."))], "scarcity"),
    ([reply(search()), reply(optimize([A])), reply(finish([{**A, "reason": "Only one snack exists."}]))], "scarcity"),
    ([reply(search()), reply(optimize([A])), reply(finish([A]), search())], "last tool call"),
    ([reply(search()), reply(optimize([A], "Buy a different basket"))], "original shopper intent"),
])
def test_invalid_or_skipped_optimization_never_returns_a_plan(responses, expected):
    chat = ScriptedChat(*responses)
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), Optimizer(), max_rounds=len(responses))(INTENT)
    assert isinstance(caught.value, PlannerError)
    assert any(expected in event["result"].get("error", {}).get("message", "")
               for event in tool_events(caught.value.decision_events))


@pytest.mark.parametrize("bad_qty", [0, -1, True, 1.5, "2", None])
def test_positive_fixed_integer_quantities_are_required(bad_qty):
    optimizer = Optimizer()
    chat = ScriptedChat(reply(search()), reply(optimize([{**A, "qty": bad_qty}])))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), optimizer, max_rounds=2)(INTENT)
    assert not optimizer.requests
    assert_error(tool_events(caught.value.decision_events)[-1], "qty must be an integer")


def test_duplicate_skus_are_rejected_instead_of_changing_fixed_quantities():
    chat = ScriptedChat(reply(search()), reply(optimize([A, A])))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), Optimizer(), max_rounds=2)(INTENT)
    assert_error(tool_events(caught.value.decision_events)[-1], "Duplicate SKUs")


def test_unknown_and_malformed_tools_are_fed_back_and_audited():
    bad = call("search_catalog", {})
    bad["function"]["arguments"] = "{bad json"

    def recover(messages):
        results = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        assert len(results) == 3 and all("error" in result for result in results)
        return reply(search(), optimize([A]), finish([A]))

    chat = ScriptedChat(reply(call("charge_payment", {"amount": 10}), bad,
                              call("search_catalog", {"unsupported": True})), recover)
    result = ToolPlanner(chat, Catalog(), Optimizer())(INTENT)
    tools = tool_events(result["decision_events"])
    assert len(tools) == 6
    assert_error(tools[0], "Unknown tool")
    assert tools[1]["result"]["error"]["type"] == "JSONDecodeError"
    assert_error(tools[2], "unknown tool arguments")


def test_trusted_search_exception_reaches_model_then_recovers():
    catalog = Catalog()
    count = 0

    def flaky(**filters):
        nonlocal count
        count += 1
        if count == 1:
            raise RuntimeError("database offline")
        return catalog(**filters)

    def retry(messages):
        assert json.loads(messages[-1]["content"])["error"]["message"] == "database offline"
        return reply(search(), optimize([A]), finish([A]))

    result = ToolPlanner(ScriptedChat(reply(search()), retry), flaky, Optimizer())(INTENT)
    assert_error(tool_events(result["decision_events"])[0], "database offline")


def test_optimizer_failure_invalidates_previous_success():
    optimizer = Optimizer()
    count = 0

    def flaky(**kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("account rules unavailable")
        return optimizer(**kwargs)

    chat = ScriptedChat(reply(search()), reply(optimize([A])), reply(optimize([A])),
                        reply(finish([A])), reply(optimize([A])), reply(finish([A])))
    result = ToolPlanner(chat, Catalog(), flaky)(INTENT)
    tools = tool_events(result["decision_events"])
    assert_error(tools[2], "account rules unavailable")
    assert_error(tools[3], "exact final lines")
    assert tools[-1]["status"] == "ok"


@pytest.mark.parametrize("output", [
    {}, {"error": "cannot optimize"}, {"lines": [{**A, "qty": 2}]},
    {"lines": [{**A, "qty": True}]}, {"lines": []},
])
def test_invalid_optimizer_results_cannot_authorize_finish(output):
    chat = ScriptedChat(reply(search()), reply(optimize([A])), reply(finish([A])))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), lambda **kwargs: output, max_rounds=3)(INTENT)
    tools = tool_events(caught.value.decision_events)
    assert tools[1]["status"] == "error"
    assert_error(tools[2], "exact final lines")


def test_optimizer_cannot_redistribute_quantities_between_existing_skus():
    output = {"lines": [{**A, "qty": 2}, {**B, "qty": 1}]}
    chat = ScriptedChat(reply(search(), search(offset=1), optimize([A, B])))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), lambda **kwargs: output, max_rounds=1)(INTENT)
    assert_error(tool_events(caught.value.decision_events)[-1], "fixed quantities")


@pytest.mark.parametrize("output", [
    {"error": "DB read denied"},
    {"products": [{"id": A["sku"]}], "total_count": 305, "has_more": False},
    {"products": [{"id": A["sku"]}], "total_count": True, "has_more": True},
    {"products": [{"name": "no SKU"}], "total_count": 1, "has_more": False},
])
def test_invalid_search_result_does_not_register_seen_skus(output):
    chat = ScriptedChat(reply(search()), reply(optimize([A])))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, lambda **filters: output, Optimizer(), max_rounds=2)(INTENT)
    tools = tool_events(caught.value.decision_events)
    assert tools[0]["status"] == "error"
    assert_error(tools[1], "successful catalog search")


def test_plain_text_final_is_a_failure_and_hidden_reasoning_is_not_audited():
    chat = ScriptedChat({"content": "I picked crackers.", "reasoning": "PRIVATE_INTERNAL_REASONING"})
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), Optimizer())(INTENT)
    assert "without calling finish_plan" in str(caught.value)
    assert "I picked crackers." == caught.value.decision_events[0]["thought"]
    assert "PRIVATE_INTERNAL_REASONING" not in json.dumps(caught.value.decision_events)


def test_round_limit_stops_at_eight_model_decisions():
    chat = ScriptedChat(*(reply(search()) for _ in range(8)))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), Optimizer(), max_rounds=8)(INTENT)
    assert len(chat.requests) == 8
    assert len(tool_events(caught.value.decision_events)) == 8
    assert "round limit" in str(caught.value)


def test_tool_limit_stops_before_twenty_fifth_callback_and_audits_rejection():
    catalog = Catalog()
    chat = ScriptedChat(reply(*(search() for _ in range(25))))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, catalog, Optimizer(), max_tool_calls=24)(INTENT)
    assert len(catalog.requests) == 24
    events = tool_events(caught.value.decision_events)
    assert len(events) == 25 and events[-1]["status"] == "rejected"
    assert "Tool call limit" in str(caught.value)


def test_finish_can_be_the_twenty_fourth_call():
    chat = ScriptedChat(reply(*(search() for _ in range(22)), optimize([A]), finish([A])))
    result = ToolPlanner(chat, Catalog(), Optimizer(), max_tool_calls=24)(INTENT)
    assert len(tool_events(result["decision_events"])) == 24


@pytest.mark.parametrize("kwargs", [{"max_rounds": 17}, {"max_tool_calls": 41}, {"max_rounds": 0}])
def test_configuration_cannot_raise_hard_bounds(kwargs):
    with pytest.raises(ValueError):
        ToolPlanner(ScriptedChat(), Catalog(), Optimizer(), **kwargs)


def test_chat_exception_preserves_existing_tool_evidence():
    def disconnect(messages):
        raise RuntimeError("model disconnected")

    chat = ScriptedChat(reply(search()), disconnect)
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), Optimizer())(INTENT)
    assert "model disconnected" in str(caught.value)
    assert tool_events(caught.value.decision_events)[0]["result"]["total_count"] == 305


@pytest.mark.parametrize("summary", [
    "No snacks are available.", "There is one snack available.",
    "The catalog has a limited selection.", "The snacks are sold out.",
    "Only\none snack is available.", "只有一種零食。",
])
def test_scarcity_claim_variants_are_rejected(summary):
    chat = ScriptedChat(reply(search()), reply(optimize([A])), reply(finish([A], summary)))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), Optimizer(), max_rounds=3)(INTENT)
    assert_error(tool_events(caught.value.decision_events)[-1], "scarcity")


def test_selection_explanation_does_not_imply_catalog_scarcity():
    summary = "I chose only snacks to fit your request."
    chat = ScriptedChat(reply(search()), reply(optimize([A])), reply(finish([A], summary)))
    assert ToolPlanner(chat, Catalog(), Optimizer())(INTENT)["thought"] == summary


def test_malformed_optimization_also_invalidates_previous_success():
    malformed = call("optimize_basket", {})
    malformed["function"]["arguments"] = "not JSON"
    chat = ScriptedChat(reply(search()), reply(optimize([A])), reply(malformed), reply(finish([A])))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), Optimizer(), max_rounds=4)(INTENT)
    assert_error(tool_events(caught.value.decision_events)[-1], "exact final lines")


def test_invalid_function_call_type_is_rejected_without_running_callback():
    malformed = search()
    malformed["type"] = "unsupported"
    catalog = Catalog()
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(ScriptedChat(reply(malformed)), catalog, Optimizer(), max_rounds=1)(INTENT)
    assert not catalog.requests
    assert_error(tool_events(caught.value.decision_events)[0], "Malformed function call")


@pytest.mark.parametrize("bad_qty", [False, 0, 2.5, "1"])
def test_finish_does_not_coerce_invalid_quantities(bad_qty):
    chat = ScriptedChat(reply(search()), reply(optimize([A])), reply(finish([{**A, "qty": bad_qty}])))
    with pytest.raises(ToolPlannerError) as caught:
        ToolPlanner(chat, Catalog(), Optimizer(), max_rounds=3)(INTENT)
    assert_error(tool_events(caught.value.decision_events)[-1], "qty must be an integer")
