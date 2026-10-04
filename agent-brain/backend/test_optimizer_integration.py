from fastapi.testclient import TestClient
from agent_graph import ShoppingAgent
from clients import PolicyClient
from fake_mall import FileMall
from server import create_app


def product(sku, name, merchant, price):
    return {'id': sku, 'name': name, 'merchant': merchant, 'category': 'Rice & Noodles',
            'price': price, 'currency': 'HKD', 'in_stock': True, 'stock': 100}


def test_agent_optimizer_tool_compares_whole_merchant_allocations(tmp_path):
    catalog = [product('r-a', 'Rice 1kg', 'Watsons', 300),
               product('r-b', 'Rice 1kg', 'PARKnSHOP', 340),
               product('o-a', 'Oats 1kg', 'Watsons', 380),
               product('o-b', 'Oats 1kg', 'PARKnSHOP', 300)]
    agent = ShoppingAgent(FileMall(products=catalog), PolicyClient(offline=True),
                          planner=lambda *a: {'query': 'rice and oats', 'qty': 1, 'needs': [
                              {'sku': 'r-a', 'query': 'Rice 1kg', 'qty': 1, 'priority': 1},
                              {'sku': 'o-a', 'query': 'Oats 1kg', 'qty': 1, 'priority': 2}]},
                          draft_path=str(tmp_path / 'drafts.sqlite3'))
    api = TestClient(create_app(agent))
    result = api.post('/agent/basket/optimize', json={
        'account_id': 'demo', 'intent': 'buy rice and oats under HK$700',
        'lines': [{'sku': 'r-a', 'qty': 1}, {'sku': 'o-a', 'qty': 1}],
    })
    assert result.status_code == 200
    optimized = result.json()
    assert 'optimize_basket' in agent.tools
    assert {line['sku'] for line in optimized['lines']} == {'r-a', 'o-b'}
    assert all(line['qty'] == 1 for line in optimized['lines'])
    assert len(optimized['settlement']['merchants']) == 2
    assert optimized['settlement']['discount'] == 75
    assert optimized['settlement']['total'] == 525
    assert optimized['optimization']['selected_effective_cost'] == 512.4
    assert optimized['optimization']['evaluations'] >= 4
    assert optimized['optimization']['global_optimum_guaranteed'] is False
    assert not agent._drafts
    planned = api.post('/agent/intent', json={'intent': 'buy rice and oats under HK$700', 'account_id': 'demo'}).json()
    assert any(step['action'] == 'optimize_basket' for step in planned['react'])
    assert {line['sku'] for line in planned['lines']} == {'r-a', 'o-b'}
    invalid = api.post('/agent/basket/optimize', json={'intent': 'food', 'lines': [{'sku': 'absent', 'qty': 1}]})
    assert invalid.status_code == 422


def test_meal_plan_invokes_the_registered_optimizer():
    from meal_plan import plan_meal
    import json
    from pathlib import Path
    catalog = json.loads((Path(__file__).parent.parent / 'hk_products_full.json').read_text(encoding='utf-8'))
    plan = plan_meal('food for 3 days for one person under HK$300', catalog)
    assert plan['meal']['optimization']['tool'] == 'optimize_basket'
    assert plan['meal']['optimization']['evaluations'] > 0
    assert any(step['action'] == 'optimize_basket' for step in plan['react_steps'])
    assert plan['needs']
