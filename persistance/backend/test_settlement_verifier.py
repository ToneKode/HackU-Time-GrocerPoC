import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from settlement_verifier import verified_settlement


def captured():
    return {'payment_id': 'pay_test', 'account_id': 'alice', 'status': 'CAPTURED',
            'rail_verified': True, 'order_id': 'ORD-1', 'receipt_id': 'RCPT-1',
            'amount': 40, 'charged': 40, 'currency': 'HKD', 'charged_currency': 'HKD',
            'rail': 'mastercard', 'merchant': 'Watsons'}


@pytest.mark.parametrize('field,value', [
    ('status', 'DRAFT'), ('status', 'REFUNDED'), ('account_id', 'bob'),
    ('payment_id', 'pay_other'), ('amount', 41), ('charged', 39),
    ('currency', 'USD'), ('charged_currency', 'USD'), ('rail_verified', False),
    ('receipt_id', None), ('charged', 'NaN'),
])
def test_rejects_unverified_or_mismatched_capture(field, value):
    payment = captured()
    payment[field] = value
    with pytest.raises(ValueError):
        verified_settlement(payment, 'alice', 'pay_test', 40, 'HKD')


def test_benefits_derive_from_verified_tender():
    result = verified_settlement(captured(), 'alice', 'pay_test', 40, 'HKD')
    assert {b['kind']: b['amount'] for b in result['benefits']} == {'membership_points': 80, 'cash': .96}
    payment = captured()
    payment.update(rail='unionpay')
    assert verified_settlement(payment, 'alice', 'pay_test', 40, 'HKD')['benefits'] == []


def test_settlement_endpoint_ignores_fabricated_rewards(monkeypatch):
    import main
    writes = []
    monkeypatch.setattr(main, 'fetch_payment', lambda *args: captured())
    monkeypatch.setattr(main.profile, 'record_paid', lambda *args, **kwargs: writes.append(kwargs) or {'order_id': 'ord_1', 'duplicate': True})
    body = main.SettleIn(amount=40, payment_id='pay_test', merchant='Fake', payment_route='visa',
                        benefits=[{'kind': 'cash', 'amount': 999999}], settlement={'benefits': [{'kind': 'cash', 'amount': 999999}]})
    main.settle_order('alice', body)
    assert writes[0]['merchant'] == 'Watsons'
    assert writes[0]['payment_route'] == 'mastercard'
    assert {b['kind']: b['amount'] for b in writes[0]['benefits']} == {'membership_points': 80, 'cash': .96}
    assert writes[0]['settlement']['source'] == 'verified_payment_capture'


def test_rejected_settlement_never_writes(monkeypatch):
    import main
    from fastapi import HTTPException
    monkeypatch.setattr(main, 'fetch_payment', lambda *args: dict(captured(), status='DRAFT'))
    monkeypatch.setattr(main.profile, 'record_paid', lambda *args, **kwargs: pytest.fail('unexpected write'))
    with pytest.raises(HTTPException) as exc:
        main.settle_order('alice', main.SettleIn(amount=40, payment_id='pay_test'))
    assert exc.value.status_code == 422


def test_payment_id_is_required():
    import main
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        main.SettleIn(amount=40)


def split_capture():
    child = captured()
    second = dict(child, payment_id='pay_second', merchant='HKTVmall', rail='unionpay', amount=60, charged=60)
    return dict(child, payment_id='pay_basket', amount=100, charged=100, rail='split',
        merchant='Watsons, HKTVmall', children=['pay_test', 'pay_second'], captures=[child, second],
        allocations=[{'merchant': 'Watsons', 'amount': 40, 'rail': 'mastercard'},
                     {'merchant': 'HKTVmall', 'amount': 60, 'rail': 'unionpay'}])


def test_split_settlement_derives_benefits_per_capture():
    result = verified_settlement(split_capture(), 'alice', 'pay_basket', 100, 'HKD')
    assert {b['kind']: b['amount'] for b in result['benefits']} == {'membership_points': 80, 'cash': .96}
    assert len(result['allocations']) == 2


@pytest.mark.parametrize('mutation', ['account', 'amount', 'rail', 'merchant', 'duplicate', 'missing'])
def test_split_settlement_rejects_invalid_child_evidence(mutation):
    payment = split_capture()
    if mutation == 'account':
        payment['captures'][1]['account_id'] = 'bob'
    elif mutation == 'amount':
        payment['captures'][1]['charged'] = 59
    elif mutation == 'rail':
        payment['captures'][1]['rail'] = 'mastercard'
    elif mutation == 'merchant':
        payment['captures'][1]['merchant'] = 'Fake'
    elif mutation == 'duplicate':
        payment['captures'][1]['payment_id'] = 'pay_test'
    else:
        payment['captures'].pop()
    with pytest.raises(ValueError):
        verified_settlement(payment, 'alice', 'pay_basket', 100, 'HKD')


def test_fetch_split_payment_reads_current_child_capture(monkeypatch):
    import httpx
    import settlement_verifier
    from fastapi import HTTPException
    parent = split_capture()
    current = dict(parent['captures'][1], status='REFUNDED')
    calls = []
    def handler(request):
        calls.append(request.url.path)
        records = {'/payment/pay_basket': parent, '/payment/pay_test': parent['captures'][0],
                   '/payment/pay_second': current}
        return httpx.Response(200, json=records[request.url.path])
    client_type = httpx.Client
    monkeypatch.setattr(settlement_verifier.httpx, 'Client', lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    payment = settlement_verifier.fetch_payment('http://mock', 'pay_basket')
    assert calls == ['/payment/pay_basket', '/payment/pay_test', '/payment/pay_second']
    with pytest.raises(ValueError, match='verified capture'):
        verified_settlement(payment, 'alice', 'pay_basket', 100, 'HKD')


def test_payment_verification_timeout_is_retryable(monkeypatch):
    import httpx
    import settlement_verifier
    from fastapi import HTTPException
    def handler(request):
        raise httpx.ReadTimeout('payment service unavailable')
    client_type = httpx.Client
    monkeypatch.setattr(settlement_verifier.httpx, 'Client', lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(HTTPException) as exc:
        settlement_verifier.fetch_payment('http://mock', 'pay_test')
    assert exc.value.status_code == 503
