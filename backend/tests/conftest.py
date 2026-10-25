import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "test.db")
os.environ["WORKER_ENABLED"] = "0"
os.environ["ADMIN_PASSWORD"] = "test-pass"
# Tests must NEVER contact anyone. Blank every delivery setting before the app is imported, so a real
# SMTP_* / TELEGRAM_BOT_TOKEN in your terminal or .env cannot leak in (the test database holds real students).
for _k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "TELEGRAM_BOT_TOKEN"):
    os.environ[_k] = ""
# The existing tests expect the reference sheet to auto-load into the (temporary) test database, whatever
# AUTOLOAD_REFERENCE is set to for your real app. Your real database is never touched: DB_PATH points to a temp file.
os.environ["AUTOLOAD_REFERENCE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app import config, notifier
from app.main import app


@pytest.fixture(autouse=True)
def _never_send(monkeypatch):
    """Second safety net: even if something re-loads real settings, force simulated mode and fail loudly on a real send."""
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "TELEGRAM_BOT_TOKEN"):
        monkeypatch.setattr(config, k, "")

    def _boom(*a, **k):
        raise AssertionError("a test tried to send a real email/Telegram message")
    monkeypatch.setattr(notifier, "send_email", _boom)
    monkeypatch.setattr(notifier, "send_telegram", _boom)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth(client):
    r = client.post("/api/auth/login", json={"email": "admin@vit.edu", "password": "test-pass"})
    return {"Authorization": "Bearer " + r.json()["token"]}
