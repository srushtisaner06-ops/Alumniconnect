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

from app import config, notifier, ratelimit
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Every test starts with empty rate-limit counters, so one test's requests never throttle another."""
    ratelimit.reset()
    yield


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


# ---------------------------------------------------------------- Phase 0 helpers
import io
import uuid
from types import SimpleNamespace

import openpyxl

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_HEADER = ["Sr. No.", "Name of the Student", "PRN No.", "Class and Div", "Contact No", "Email-Id",
           "Name of the Employer", "Package", "Position", "Appointment letter reference number and Date",
           "Appointment letter PDF Link"]


@pytest.fixture
def import_people(client, auth):
    """import_people([(name, prn), ...], year) -> {prn: alumni_id}. Each test uses its own PRNs so tests stay independent."""
    def make(people, year=2041):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([f"AY: {year - 1}-{str(year)[2:]} Placement"])
        ws.append(_HEADER)
        for i, (name, prn) in enumerate(people, 1):
            ws.append([i, name, prn, "BTech", "9876500000", f"{name.split()[0].lower()}{prn}@example.com", "Acme Corp", 7.5, "Engineer", None, None])
        b = io.BytesIO()
        wb.save(b)
        r = client.post("/api/import", headers=auth, files={"file": (f"p0_{uuid.uuid4().hex[:6]}.xlsx", b.getvalue(), XLSX_TYPE)},
                        data={"graduation_year": str(year)})
        assert r.status_code == 200, r.text
        return {prn: client.get(f"/api/alumni?search={prn}", headers=auth).json()["items"][0]["id"] for _, prn in people}
    return make


@pytest.fixture
def account(client, auth):
    """account(role, alumni_id=None) -> user with working auth headers. A fresh user per call."""
    def make(role, alumni_id=None, password="Str0ng-Pass-1"):
        email = f"{role.lower()}.{uuid.uuid4().hex[:8]}@example.com"
        r = client.post("/api/users", headers=auth, json={"email": email, "password": password, "role": role, "alumni_id": alumni_id})
        assert r.status_code == 200, r.text
        login = client.post("/api/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        return SimpleNamespace(id=r.json()["id"], email=email, password=password, token=login.json()["token"],
                               headers={"Authorization": "Bearer " + login.json()["token"]})
    return make
