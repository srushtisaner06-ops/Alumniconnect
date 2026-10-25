import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "test.db")
os.environ["WORKER_ENABLED"] = "0"
os.environ["ADMIN_PASSWORD"] = "test-pass"
os.environ["AUTOLOAD_REFERENCE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth(client):
    r = client.post("/api/auth/login", json={"email": "admin@vit.edu", "password": "test-pass"})
    return {"Authorization": "Bearer " + r.json()["token"]}
