import httpx
import pytest


def _draft(c):
    return c.post('/payment/draft', json={'account_id': 'alice', 'amount': 40, 'merchant': 'Watsons'}).json()


def test_timeout_recovery_uses_persisted_key_after_token_expiry(c, monkeypatch):
    import main
    from rails import charge_local
    calls = []
    approved = None

    def rail(**kwargs):
        nonlocal approved
        calls.append(kwargs['idempotency_key'])
        if approved is None:
            approved = charge_local(kwargs['amount'], kwargs['rail'], kwargs['idempotency_key'])
            raise httpx.ReadTimeout('response lost after charge')
        return approved

    monkeypatch.setattr(main, 'charge', rail)
    draft = _draft(c)
    first = c.post('/payment/authorize', json={'payment_id': draft['payment_id'], 'idempotency_key': 'caller-key'}).json()
    assert first['status'] == 'PENDING'
    persisted = main.store.get(draft['payment_id'])
    assert persisted['attempt_key'] == calls[0]
    assert not main.store.mark_jti_used(persisted['token_jti'])
    monkeypatch.setattr(main, 'verify', lambda *args: (_ for _ in ()).throw(ValueError('expired')))
    recovered = c.post(f"/payment/{draft['payment_id']}/recover").json()
    assert recovered['status'] == 'CAPTURED'
    assert recovered['rail_verified'] is True
    assert recovered['order_id'] == approved['order_id']
    replay = c.post('/payment/authorize', json={'payment_id': draft['payment_id'], 'idempotency_key': 'changed'}).json()
    assert replay['order_id'] == recovered['order_id']
    assert calls == [persisted['attempt_key'], persisted['attempt_key']]


@pytest.mark.parametrize('field,value', [('charged', 41), ('currency', 'USD'), ('currency', None), ('order_id', None)])
def test_bad_rail_result_never_captures(c, monkeypatch, field, value):
    import main
    from rails import charge_local
    result = charge_local(40, 'mastercard', 'x')
    result[field] = value
    monkeypatch.setattr(main, 'charge', lambda **kwargs: result)
    draft = _draft(c)
    response = c.post('/payment/authorize', json={'payment_id': draft['payment_id']}).json()
    assert response['status'] == 'PENDING'
    assert response['error'] == 'rail_amount_or_currency_mismatch'
    assert not response.get('rail_verified')


def test_recovery_requires_started_attempt(c):
    draft = _draft(c)
    assert c.post(f"/payment/{draft['payment_id']}/recover").status_code == 409


def test_local_rail_replay_has_same_capture():
    from rails import charge_local
    first = charge_local(40, 'mastercard', 'stable')
    second = charge_local(40, 'mastercard', 'stable')
    assert first['order_id'] == second['order_id']
    assert first['auth_id'] == second['auth_id']


def test_mysql_extra_roundtrip_keeps_recovery_context():
    from mysql_store import _to_row, _row_to_record
    from store import draft_record
    record = draft_record(account_id='alice', amount=40, currency='HKD', merchant='Watsons', rail='mastercard', purpose='cart', intent='', cart_hash='', token={'jti': 'j', 'token': 't', 'expires_at': 2000000000}, recommendation={})
    record.update(status='PENDING', attempt_key='stable', attempt_started=True)
    loaded = _row_to_record(_to_row(record))
    assert loaded['attempt_key'] == 'stable'
    assert loaded['attempt_started'] is True
    assert loaded['status'] == 'PENDING'
