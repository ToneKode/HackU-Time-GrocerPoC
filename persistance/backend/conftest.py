import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Separate database. /demo/reset truncates audit and spend, so this suite
# must not use the shop database time_grocer.
os.environ.setdefault(
    "DATABASE_URL", "mysql://tg:tg@127.0.0.1:3306/time_grocer_test"
)
os.environ["REDIS_URL"] = "fakeredis://"
os.environ["ESCALATION_TTL_SECONDS"] = "2"
os.environ["DEMO_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient

from db import apply_schema, ensure_database
from main import app
from config import settings


@pytest.fixture()
def c():
    s = settings()
    ensure_database(s["database_url"])
    apply_schema(s["database_url"], s["schema_path"])
    with TestClient(app) as client:
        client.post("/demo/reset")
        yield client
