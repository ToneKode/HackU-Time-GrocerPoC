import pytest
import main


def quote():
    return {"total": 80, "merchants": [{"merchant": "Watsons", "total": 80}],
            "lines": [{"sku": "a", "qty": 1}], "promotion_snapshot": {"rules": {
                "version": 7, "payment_promotions": [
                    {"route": "mastercard", "kind": "cash", "rate": 0.024, "merchant": "", "enabled": True},
                    {"route": "mastercard", "kind": "asiamiles", "rate": 0.1, "merchant": "", "enabled": True}]}}}


def test_draft_fetches_server_quote_and_preserves_it(c, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "fetch_market_quote", lambda lines: calls.append(lines) or quote())
    result = c.post("/payment/draft", json={"account_id": "a", "amount": 80, "merchant": "Watsons",
                                           "lines": [{"sku": "a", "qty": 1}], "promotion_snapshot": {"fake": True}})
    assert result.status_code == 200
    assert result.json()["market_quote"] == quote()
    assert calls == [[{"sku": "a", "qty": 1}]]
    captured = c.post("/payment/authorize", json={"payment_id": result.json()["payment_id"]})
    assert captured.json()["status"] == "CAPTURED"
    assert captured.json()["market_quote"] == quote()


def test_changed_price_rejected_before_draft(c, monkeypatch):
    monkeypatch.setattr(main, "fetch_market_quote", lambda lines: quote())
    result = c.post("/payment/draft", json={"amount": 100, "merchant": "Watsons", "lines": [{"sku": "a", "qty": 1}]})
    assert result.status_code == 409


def test_basket_attaches_one_snapshot_to_parent_and_children(c, monkeypatch):
    import httpx
    client_type = httpx.Client
    monkeypatch.setattr(main.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=quote()))))
    result = c.post("/payment/basket/draft", json={"account_id": "a", "groups": [{"merchant": "Watsons", "amount": 80, "rail": "mastercard"}], "lines": [{"sku": "a", "qty": 1}]})
    assert result.status_code == 200, result.text
    parent = result.json()
    assert parent["market_quote"] == quote()
    assert main.store.get(parent["children"][0])["market_quote"] == quote()
