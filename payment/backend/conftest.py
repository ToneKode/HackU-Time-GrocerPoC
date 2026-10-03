import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ["PAYMENT_TOKEN_SECRET"] = "test-payment-secret-32chars-min!!"
os.environ["PAYMENT_TOKEN_TTL_SECONDS"] = "60"
os.environ["DEMO_MODE"] = "true"
os.environ["MOCK_ACQUIRER_URL"] = ""
os.environ["REDIS_URL"] = ""

import pytest
from fastapi.testclient import TestClient

# Re-import after env
import importlib
import main as payment_main

importlib.reload(payment_main)
from main import app, store


@pytest.fixture()
def c():
    store.reset()
    with TestClient(app) as client:
        yield client
