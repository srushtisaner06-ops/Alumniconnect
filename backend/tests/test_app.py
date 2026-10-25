import io
from pathlib import Path

import openpyxl

REF = Path(__file__).resolve().parent.parent / "data" / "reference_placement.xlsx"


def xlsx_bytes(rows, header=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["AY: 2024-25 Placement"])
    ws.append(header or ["Sr. No.", "Name of the Student", "PRN No.", "Class and Div", "Contact No", "Email-Id",
                         "Name of the Employer", "Package", "Position", "Appointment letter reference number and Date",
                         "Appointment letter PDF Link"])
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


GOOD = [1, "Test Student", 12111111, "BTech", "9876543210", "t.student@vit.edu", "Acme", 6.5, "SDE", None, None]


def test_login(client):
    assert client.post("/api/auth/login", json={"email": "admin@vit.edu", "password": "x"}).status_code == 401
    assert client.get("/api/alumni").status_code == 401


def test_real_data_loaded_no_seed(client, auth):
    d = client.get("/api/dashboard", headers=auth).json()
    assert d["summary"]["total"] == 51          # unique PRNs in the sheet
    assert d["placement"]["offers"] == 56       # rows in the sheet
    assert d["placement"]["multi_offer_students"] == 5
    assert d["placement"]["highest_package"] == 32.75
    assert d["placement"]["final_year_students"] == 77


def test_prn_search_returns_single(client, auth):
    r = client.get("/api/alumni?search=12210396", headers=auth).json()
    assert r["total"] == 1 and r["items"][0]["name"].upper().startswith("VEDANT")
    assert len(r["items"][0]["offers"]) == 2
    assert client.get("/api/alumni?search=99999999", headers=auth).json()["total"] == 0
    assert client.get("/api/alumni?search=deloitte", headers=auth).json()["total"] == 2
    assert "token" not in r["items"][0]


def test_import_validate_reference_ok(client, auth):
    r = client.post("/api/import/validate", headers=auth, files={"file": ("a.xlsx", REF.read_bytes())}).json()
    assert r["ok"] and r["summary"]["unique_students"] == 51 and r["already_in_database"] == 51


def test_import_rejects_wrong_format(client, auth):
    bad = xlsx_bytes([["x", "y"]], header=["Student", "Roll", "Mail"])
    r = client.post("/api/import", headers=auth, files={"file": ("a.xlsx", bad)})
    assert r.status_code == 422 and r.json()["detail"]["report"]["missing_columns"]
    r = client.post("/api/import", headers=auth, files={"file": ("a.txt", b"hello")})
    assert r.status_code == 422


def test_import_row_errors_strict_then_skip(client, auth):
    bad_row = [2, "Bad Row", 123, "BTech", "12345", "nope", "Acme", "abc", None, None, None]
    data = xlsx_bytes([GOOD, bad_row])
    rep = client.post("/api/import/validate", headers=auth, files={"file": ("a.xlsx", data)}).json()
    cols = {e["column"] for e in rep["errors"]}
    assert {"PRN No.", "Contact No", "Email-Id", "Package"} <= cols and rep["graduation_year"] == 2025
    assert client.post("/api/import", headers=auth, files={"file": ("a.xlsx", data)}).status_code == 422
    ok = client.post("/api/import", headers=auth, data={"skip_invalid": "true"}, files={"file": ("a.xlsx", data)})
    assert ok.status_code == 200 and ok.json()["added"] == 1 and ok.json()["skipped_rows"] == 1
    assert client.get("/api/alumni?search=12111111", headers=auth).json()["total"] == 1


def test_import_replace_and_reload(client, auth):
    r = client.post("/api/import", headers=auth, data={"replace": "true"}, files={"file": ("a.xlsx", REF.read_bytes())})
    assert r.status_code == 200 and r.json()["added"] == 51
    assert client.get("/api/dashboard", headers=auth).json()["summary"]["total"] == 51


def _token(client, auth, prn):
    # token is only exposed through the faculty detail link
    a = client.get(f"/api/alumni?search={prn}", headers=auth).json()["items"][0]
    link = client.get(f"/api/alumni/{a['id']}", headers=auth).json()["link"]
    return a["id"], link.split("token=")[1]


def test_public_form_and_submit(client, auth):
    assert client.get("/api/public/form?token=bogus").status_code == 404
    aid, tok = _token(client, auth, 12211741)
    f = client.get(f"/api/public/form?token={tok}").json()
    assert f["status"] == "PENDING" and f["prefill"]["company"] == "Principal Global"
    assert client.post("/api/public/submit", json={"token": tok, "career_status": "EMPLOYMENT", "details": {"company": "X"}}).status_code == 422
    body = {"token": tok, "career_status": "HIGHER_STUDIES",
            "details": {"university": "MIT", "country": "USA", "degree": "MS", "specialization": "AI"}}
    assert client.post("/api/public/submit", json=body).json()["already_submitted"] is False
    assert client.post("/api/public/submit", json=body).json()["already_submitted"] is True
    assert client.get(f"/api/alumni/{aid}", headers=auth).json()["status"] == "COMPLETED"


CAMP = {"name": "Round 1", "channel": "email", "interval_hours": 1, "max_attempts": 2, "batch_size": 10}


def test_campaign_validation(client, auth):
    assert client.post("/api/campaigns", headers=auth, json={**CAMP, "email_body": "hi {{nope}} {{unique_link}}"}).status_code == 422
    assert client.post("/api/campaigns", headers=auth, json={**CAMP, "email_body": "no link"}).status_code == 422


def test_campaign_flow(client, auth):
    cid = client.post("/api/campaigns", headers=auth, json=CAMP).json()["id"]
    assert client.post(f"/api/campaigns/{cid}/run-now", headers=auth).status_code == 409   # not started
    client.post(f"/api/campaigns/{cid}/start", headers=auth)
    # one person unsubscribed, one already completed (from earlier test)
    a = client.get("/api/alumni?search=12211777", headers=auth).json()["items"][0]
    client.patch(f"/api/alumni/{a['id']}", headers=auth, json={"unsubscribed": True})
    res = client.post(f"/api/campaigns/{cid}/run-now", headers=auth).json()
    assert res["simulated"] == 10 and res["remaining"] == 39     # 51 - 1 completed - 1 unsubscribed = 49; batch of 10
    logs = client.get(f"/api/reminders?campaign_id={cid}", headers=auth).json()["items"]
    names = {l["prn"] for l in logs}
    assert "12211741" not in names and "12211777" not in names and all(l["status"] == "SIMULATED" for l in logs)
    # interval not elapsed -> the 10 already reminded are not eligible again
    res2 = client.post(f"/api/campaigns/{cid}/run-now", headers=auth).json()
    assert res2["simulated"] == 10 and {l["prn"] for l in client.get(f"/api/reminders?campaign_id={cid}", headers=auth).json()["items"]}.__len__() == 20
    # pause stops processing
    client.post(f"/api/campaigns/{cid}/pause", headers=auth)
    assert client.post(f"/api/campaigns/{cid}/run-now", headers=auth).status_code == 409


def test_submission_stops_reminders(client, auth):
    cid = client.post("/api/campaigns", headers=auth, json={**CAMP, "name": "Round 2", "batch_size": 500}).json()["id"]
    client.post(f"/api/campaigns/{cid}/start", headers=auth)
    aid, tok = _token(client, auth, 12210175)
    client.post("/api/public/submit", json={"token": tok, "career_status": "EMPLOYMENT",
                "details": {"company": "Amazon", "designation": "SDE", "industry": "Tech"}})
    client.post(f"/api/campaigns/{cid}/run-now", headers=auth)
    logs = client.get(f"/api/reminders?campaign_id={cid}", headers=auth).json()["items"]
    assert "12210175" not in {l["prn"] for l in logs}


def test_undo_delete(client, auth):
    a = client.get("/api/alumni?search=12210472", headers=auth).json()["items"][0]
    assert client.delete(f"/api/alumni/{a['id']}", headers=auth).status_code == 200
    assert client.get("/api/alumni?search=12210472", headers=auth).json()["total"] == 0
    assert client.get("/api/undo", headers=auth).json()["next"].startswith("Deleted")
    assert client.post("/api/undo", headers=auth).status_code == 200
    back = client.get("/api/alumni?search=12210472", headers=auth).json()
    assert back["total"] == 1 and len(back["items"][0]["offers"]) == 1


def test_exports(client, auth):
    for scope in ("submissions", "placement"):
        for fmt in ("csv", "xlsx"):
            r = client.get(f"/api/reports/export?scope={scope}&format={fmt}", headers=auth)
            assert r.status_code == 200 and len(r.content) > 200
    # placement export round-trips through the importer (same format as the reference)
    r = client.get("/api/reports/export?scope=placement&format=xlsx", headers=auth)
    rep = client.post("/api/import/validate", headers=auth, data={"graduation_year": "2026"}, files={"file": ("x.xlsx", r.content)}).json()
    assert rep["ok"], rep["errors"][:3]


def test_engine_matches_fallback():
    from app import engine, config
    recs = [{"id": i, "prn": f"1221{i:04d}", "graduation_year": 2020 + i % 3, "status": "PENDING", "priority": (i * 7) % 5} for i in range(1, 30)]
    cpp = engine.schedule(recs, 4)
    old = config.ENGINE_PATH
    config.ENGINE_PATH = "/nonexistent"
    py = engine.schedule(recs, 4)
    config.ENGINE_PATH = old
    assert cpp["order"] == py["order"] and cpp["batches"] == py["batches"]
