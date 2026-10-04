from copy import deepcopy
from basket_payments import authorize_basket


class Store:
    def __init__(self, records):
        self.records = deepcopy(records)
    def get(self, pid):
        return deepcopy(self.records.get(pid))
    def put(self, row):
        self.records[row['payment_id']] = deepcopy(row)


class Request:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_partial_merchant_capture_resumes_without_charging_first_merchant_twice():
    parent = {'payment_id': 'basket', 'children': ['a', 'b'], 'account_id': 'alice',
              'status': 'DRAFT', 'amount': 150, 'currency': 'HKD'}
    store = Store({'basket': parent})
    attempts = []
    captured = {}
    def authorize(body):
        if body.payment_id in captured:
            return captured[body.payment_id]
        attempts.append(body.payment_id)
        if body.payment_id == 'b' and attempts.count('b') == 1:
            return {'payment_id': 'b', 'status': 'PENDING', 'error': 'timeout'}
        row = {'payment_id': body.payment_id, 'account_id': 'alice', 'status': 'CAPTURED',
               'amount': 100 if body.payment_id == 'a' else 50,
               'charged': 100 if body.payment_id == 'a' else 50,
               'rail_verified': True, 'charged_currency': 'HKD', 'updated_at': 'today'}
        captured[body.payment_id] = row
        return row
    first = authorize_basket(store, authorize, Request, parent, True)
    assert first['status'] == 'PENDING'
    assert first['partial_captures'] == ['a']
    resumed = authorize_basket(store, authorize, Request, store.get('basket'), True)
    assert resumed['status'] == 'CAPTURED'
    assert resumed['charged'] == 150
    assert len(resumed['captures']) == 2
    assert attempts == ['a', 'b', 'b']
    repeated = authorize_basket(store, authorize, Request, store.get('basket'), True)
    assert repeated['order_id'] == resumed['order_id']
    assert attempts == ['a', 'b', 'b']


def test_basket_api_timeout_recovery_and_one_approval(c, monkeypatch):
    import httpx
    import main
    from rails import charge_local
    calls = []
    lost = False
    def rail(**kwargs):
        nonlocal lost
        calls.append((kwargs['amount'], kwargs['idempotency_key']))
        result = charge_local(kwargs['amount'], kwargs['rail'], kwargs['idempotency_key'])
        if kwargs['amount'] == 210 and not lost:
            lost = True
            raise httpx.ReadTimeout('lost capture response')
        return result
    monkeypatch.setattr(main, 'charge', rail)
    response = c.post('/payment/basket/draft', json={'account_id': 'student_mock', 'intent': 'weekly shop',
        'groups': [{'merchant': 'Watsons', 'amount': 200, 'rail': 'mastercard'},
                   {'merchant': 'HKTVmall', 'amount': 210, 'rail': 'unionpay'}]})
    assert response.status_code == 200
    draft = response.json()
    pid = draft['payment_id']
    assert c.post('/payment/authorize', json={'payment_id': pid}).status_code == 403
    assert calls == []
    first = c.post('/payment/authorize', json={'payment_id': pid, 'step_up_confirmed': True}).json()
    assert first['status'] == 'PENDING'
    assert len(first['partial_captures']) == 1
    recovered = c.post(f'/payment/{pid}/recover').json()
    assert recovered['status'] == 'CAPTURED'
    assert recovered['charged'] == 410
    assert len(recovered['captures']) == 2
    assert calls[1] == calls[2]
    assert len(calls) == 3
    assert c.post(f'/payment/{pid}/recover').json()['order_id'] == recovered['order_id']
    assert c.post('/payment/authorize', json={'payment_id': pid}).json()['status'] == 'CAPTURED'
    assert all('token' not in child for child in recovered['captures'])


def test_basket_rejects_fractional_cents_before_creating_children(c):
    import main
    response = c.post('/payment/basket/draft', json={'account_id': 'student_mock',
        'groups': [{'merchant': 'Watsons', 'amount': .001, 'rail': 'mastercard'}]})
    assert response.status_code == 422
    assert not main.store._mem


def test_basket_recovery_survives_all_child_tokens_expiring(c, monkeypatch):
    import httpx
    import main
    from rails import charge_local
    calls = []
    def rail(**kwargs):
        calls.append(kwargs['idempotency_key'])
        if len(calls) == 1:
            raise httpx.ReadTimeout('first merchant timed out')
        return charge_local(kwargs['amount'], kwargs['rail'], kwargs['idempotency_key'])
    monkeypatch.setattr(main, 'charge', rail)
    draft = c.post('/payment/basket/draft', json={'account_id': 'student_mock',
        'groups': [{'merchant': 'Watsons', 'amount': 40, 'rail': 'mastercard'},
                   {'merchant': 'HKTVmall', 'amount': 50, 'rail': 'unionpay'}]}).json()
    first = c.post('/payment/authorize', json={'payment_id': draft['payment_id'], 'step_up_confirmed': True}).json()
    assert first['status'] == 'PENDING'
    assert all(main.store.get(pid)['attempt_started'] for pid in draft['children'])
    monkeypatch.setattr(main, 'verify', lambda *args: (_ for _ in ()).throw(ValueError('expired')))
    recovered = c.post(f"/payment/{draft['payment_id']}/recover").json()
    assert recovered['status'] == 'CAPTURED'
    assert calls[0] == calls[1]


def test_client_split_payment_and_scoped_escalation_contracts():
    import importlib.util
    import json
    import sys
    from pathlib import Path
    import httpx
    root = Path(__file__).resolve().parents[2] / 'agent-brain' / 'backend'
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location('payment_test_agent_clients', root / 'clients.py')
    clients = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clients)
    requests = []
    def handler(request):
        requests.append((request.url.path, json.loads(request.content) if request.content else None))
        if request.url.path == '/create_escalation':
            return httpx.Response(200, json={'escalation_id': 'esc_test'})
        return httpx.Response(200, json={'payment_id': 'pay_test', 'status': 'PENDING'})
    http = httpx.Client(base_url='http://mock', transport=httpx.MockTransport(handler))
    payment = clients.PaymentClient(http=http)
    payment.draft_basket(account_id='student_mock', intent='shop', groups=[
        {'merchant': 'Watsons', 'payment': {'amount': 40, 'route': 'mastercard'}}])
    payment.recover('pay_test')
    assert requests[:2] == [('/payment/basket/draft', {'account_id': 'student_mock', 'intent': 'shop',
        'groups': [{'merchant': 'Watsons', 'amount': 40, 'rail': 'mastercard'}]}),
        ('/payment/pay_test/recover', None)]
    policy = clients.PolicyClient(http=http)
    draft = {'amount': 40, 'currency': 'HKD', 'merchant': 'Watsons', 'sku': 'mock_sku', 'reason': 'approval'}
    policy.create_escalation(draft, account_id='student_mock', run_id='run_mock', order_id='ord_mock')
    payload = requests[-1][1]
    assert (payload['account_id'], payload['run_id'], payload['order_id']) == ('student_mock', 'run_mock', 'ord_mock')
    assert 'account_id' not in draft
    policy.create_escalation(dict(draft, account_id='student_mock', run_id='run_legacy', order_id='ord_legacy'))
    assert requests[-1][1]['order_id'] == 'ord_legacy'


def test_mysql_roundtrip_keeps_basket_context(c):
    from mysql_store import _to_row, _row_to_record
    import main
    draft = c.post('/payment/basket/draft', json={'account_id': 'student_mock',
        'groups': [{'merchant': 'Watsons', 'amount': 40, 'rail': 'mastercard'}]}).json()
    record = main.store.get(draft['payment_id'])
    loaded = _row_to_record(_to_row(record))
    assert loaded['children'] == record['children']
    assert loaded['allocations'] == record['allocations']
    assert loaded['rail'] == 'split'
