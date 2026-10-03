import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault(
    "DATABASE_URL", "postgresql://tg:tg@127.0.0.1:5432/time_grocer"
)
os.environ["REDIS_URL"] = "fakeredis://"
os.environ["ESCALATION_TTL_SECONDS"] = "2"
os.environ["DEMO_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient

from db import apply_schema
from main import app
from config import settings


@pytest.fixture()
def c():
    s = settings()
    apply_schema(s["database_url"], s["schema_path"])
    with TestClient(app) as client:
        client.post("/demo/reset")
        yield client
