import httpx
from clients import ProfileClient
from agent_graph import ShoppingAgent
from clients import PaymentClient, PolicyClient
from fake_mall import FileMall


class Profile:
    def __init__(self):
        self.fail = True
        self.calls = []

    def settle(self, account_id, body):
        self.calls.append((account_id, body))
        if self.fail:
            return None
        return {"order_id": "saved-1"}


def agent(**kwargs):
    return ShoppingAgent(FileMall(), PolicyClient(offline=True), planner=lambda *args: {}, **kwargs)


def test_settlement_allows_payment_verification_and_mysql_latency():
    def handle(request):
        if request.url.path.endswith('/orders/settle'):
            assert request.extensions['timeout']['read'] >= 15
            return httpx.Response(200, json={'order_id': 'saved-1'})
        assert request.extensions['timeout']['read'] == 0.8
        return httpx.Response(200, json={'id': 'alice'})

    client = ProfileClient(http=httpx.Client(base_url='http://profile', timeout=0.8,
                                            transport=httpx.MockTransport(handle)))
    assert client.settle('alice', {'payment_id': 'p1'})['order_id'] == 'saved-1'
    assert client.get_profile('alice')['id'] == 'alice'


def test_edited_nonmeal_basket_retains_user_budget():
    a = agent()
    result = a.confirm_basket("buy toilet paper under HK$50", [{"sku": "SKU001", "qty": 3}])
    assert result["quote"]["total_landed_cost"] == 119.7
    assert result["status"] == "NEEDS_INPUT"
    assert result["policy"]["rule"] == "user_max_total"
    assert result["payment_draft"] is None


def test_captured_order_can_be_saved_after_restart(tmp_path):
    path = str(tmp_path / "drafts.sqlite3")
    profile = Profile()
    a = agent(profile=profile, draft_path=path)
    a._drafts["pay-1"] = {"account_id": "alice", "intent": "food", "lines": [], "settlement": {"total": 100}}
    payment = {"charged": 100, "currency": "HKD", "payment_route": "mastercard"}
    assert a._save_paid("pay-1", payment, "alice") is False
    restarted = agent(profile=profile, draft_path=path)
    assert restarted.recover_orders("bob") == {"recovered": [], "pending": []}
    profile.fail = False
    assert restarted.recover_orders("alice") == {"recovered": ["pay-1"], "pending": []}
    assert restarted.recover_orders("alice") == {"recovered": [], "pending": []}
    assert len(profile.calls) == 2


def test_payment_client_recovers_after_transient_connection_error():
    calls = []
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("offline briefly", request=request)
        return httpx.Response(200, json={"payment_id": "p1"})
    client = PaymentClient(http=httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)))
    assert client.draft(amount=100, merchant="Watsons") is None
    assert client.draft(amount=100, merchant="Watsons")["payment_id"] == "p1"
    assert len(calls) == 2


class PendingPayments:
    def __init__(self):
        self.recover_calls = []

    def get_payment(self, payment_id):
        return {"payment_id": payment_id, "account_id": "alice", "status": "PENDING"}

    def recover(self, payment_id):
        self.recover_calls.append(payment_id)
        return {"payment_id": payment_id, "account_id": "alice", "status": "CAPTURED",
                "charged": 100, "currency": "HKD", "rail": "mastercard", "order_id": "rail-1"}


def test_pending_payment_recovery_is_scoped_and_saves_original_basket(tmp_path):
    payments = PendingPayments()
    profile = Profile()
    profile.fail = False
    a = agent(profile=profile, payments=payments, draft_path=str(tmp_path / "drafts.sqlite3"))
    a._drafts["pay-1"] = {"account_id": "alice", "intent": "food", "lines": [], "settlement": {"total": 100}}
    wrong = a.recover_payment("pay-1", "bob")
    assert wrong["error"] == "payment_account_mismatch"
    assert payments.recover_calls == []
    recovered = a.recover_payment("pay-1", "alice")
    assert recovered["success"] is True
    assert recovered["settlement_saved"] is True
    assert payments.recover_calls == ["pay-1"]
    assert profile.calls[0][0] == "alice"


def test_recovery_checks_payment_owner_after_local_draft_is_gone(tmp_path):
    from fastapi.testclient import TestClient
    from server import create_app

    payments = PendingPayments()
    a = agent(payments=payments, draft_path=str(tmp_path / "drafts.sqlite3"))
    api = TestClient(create_app(a))
    response = api.post("/agent/payment/recover", json={"payment_id": "pay-1", "account_id": "bob"})
    assert response.status_code == 200
    assert response.json()["error"] == "payment_account_mismatch"
    assert payments.recover_calls == []
    own = api.post("/agent/payment/recover", json={"payment_id": "pay-1", "account_id": "alice"})
    assert own.status_code == 200
    assert own.json()["success"] is True


def test_approved_basket_resumes_all_merchants_and_preserves_owner(tmp_path):
    class BasketPayments:
        def draft_basket(self, **kwargs):
            self.groups = kwargs["groups"]
            return {"payment_id": "basket-1", "status": "DRAFT", "amount": sum(g["payment"]["amount"] for g in self.groups), "rail": "split"}

    payments = BasketPayments()
    a = agent(payments=payments, draft_path=str(tmp_path / "drafts.sqlite3"))
    plan = a.confirm_basket("buy shampoo and toilet paper", [{"sku": "SKU018", "qty": 2}, {"sku": "SKU001", "qty": 1}], account_id="alice")
    assert plan["status"] == "ESCALATED"
    eid = plan["escalation"]["escalation_id"]
    record = a.policy.memory[eid]
    assert record["account_id"] == "alice" and record["order_id"] and record["run_id"]
    record["status"] = "APPROVED"
    wrong = a.run("buy shampoo and toilet paper", 0, account_id="bob", escalation_id=eid)
    assert wrong["status"] == "ABORTED"
    resumed = a.run("buy shampoo and toilet paper", 0, account_id="alice", escalation_id=eid)
    assert resumed["status"] == "READY"
    assert resumed["payment_draft"]["payment_id"] == "basket-1"
    assert len(payments.groups) == 2
    assert {line["sku"] for line in resumed["lines"]} == {"SKU018", "SKU001"}
