"""Recipient selection: batches, imported files, individuals, combined + deduplicated, preview, worker filter.
Self-contained: creates its own alumni (PRNs 31000001-31000004, years 2031/2032) so other tests are unaffected."""
import io

import openpyxl

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADER = ["Sr. No.", "Name of the Student", "PRN No.", "Class and Div", "Contact No", "Email-Id",
          "Name of the Employer", "Package", "Position", "Appointment letter reference number and Date",
          "Appointment letter PDF Link"]


def _xlsx(people):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["AY: 2030-31 Placement"])
    ws.append(HEADER)
    for i, (name, prn) in enumerate(people, 1):
        ws.append([i, name, prn, "BTech", "9876500000", f"{name.split()[0].lower()}@example.com", "Acme", 5.0, "SDE", None, None])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _import(client, auth, filename, people, year):
    r = client.post("/api/import", headers=auth, files={"file": (filename, _xlsx(people), XLSX)}, data={"graduation_year": str(year)})
    assert r.status_code == 200, r.text
    return r.json()["import_id"]


def _alumnus(client, auth, prn):
    return client.get(f"/api/alumni?search={prn}", headers=auth).json()["items"][0]


def _setup(client, auth):
    """File A = PRN 1,2,3 (year 2031). File B = PRN 3,4 -> PRN 3 moves to 2032 and belongs to BOTH files."""
    a = _import(client, auth, "fileA.xlsx", [("Aaa One", 31000001), ("Bbb Two", 31000002), ("Ccc Three", 31000003)], 2031)
    b = _import(client, auth, "fileB.xlsx", [("Ccc Three", 31000003), ("Ddd Four", 31000004)], 2032)
    return a, b


def test_options_show_batches_and_import_history(client, auth):
    a, b = _setup(client, auth)
    opts = client.get("/api/recipients/options", headers=auth).json()
    files = {i["id"]: i for i in opts["imports"]}
    assert files[a]["filename"] == "fileA.xlsx" and files[a]["total"] == 3
    assert files[b]["filename"] == "fileB.xlsx" and files[b]["total"] == 2          # same alumnus can sit in two files
    years = {x["year"]: x["total"] for x in opts["batches"]}
    assert years[2031] == 2 and years[2032] == 2                                     # PRN 3 was moved to 2032 by file B


def test_search_by_name_prn_email(client, auth):
    assert client.get("/api/recipients/search?q=31000004", headers=auth).json()["items"][0]["name"] == "Ddd Four"
    assert client.get("/api/recipients/search?q=ccc", headers=auth).json()["items"][0]["prn"] == "31000003"
    assert client.get("/api/recipients/search?q=a", headers=auth).json()["items"] == []        # too short


def test_combined_selection_is_deduplicated_and_preview_buckets(client, auth):
    opts = client.get("/api/recipients/options", headers=auth).json()
    b = next(i["id"] for i in opts["imports"] if i["filename"] == "fileB.xlsx")
    ids = {p: _alumnus(client, auth, p)["id"] for p in (31000001, 31000002, 31000003, 31000004)}
    # batch 2031 = {1,2}; file B = {3,4}; individual {1} overlaps -> 4 people, not 5
    sel = {"batches": [2031], "import_ids": [b], "alumni_ids": [ids[31000001]]}
    pv = client.post("/api/recipients/preview", headers=auth, json={"recipients": sel, "channel": "email", "max_attempts": 3}).json()
    assert pv == {"selected": 4, "eligible": 4, "completed": 0, "unsubscribed": 0, "no_contact": 0, "attempts_used": 0}

    # one completes the form, one unsubscribes
    link = client.get(f"/api/alumni/{ids[31000001]}", headers=auth).json()["link"]
    client.post("/api/public/submit", json={"token": link.split("token=")[1], "career_status": "EMPLOYMENT",
                "details": {"company": "X", "designation": "Y", "industry": "Z"}})
    client.patch(f"/api/alumni/{ids[31000002]}", headers=auth, json={"unsubscribed": True})
    pv = client.post("/api/recipients/preview", headers=auth, json={"recipients": sel, "channel": "email", "max_attempts": 3}).json()
    assert pv == {"selected": 4, "eligible": 2, "completed": 1, "unsubscribed": 1, "no_contact": 0, "attempts_used": 0}

    # Telegram: nobody has a chat id yet -> the two pending people have no usable contact
    pv = client.post("/api/recipients/preview", headers=auth, json={"recipients": sel, "channel": "telegram", "max_attempts": 3}).json()
    assert pv["no_contact"] == 2 and pv["eligible"] == 0
    client.patch(f"/api/alumni/{ids[31000004]}", headers=auth, json={"telegram_chat_id": "12345"})
    pv = client.post("/api/recipients/preview", headers=auth, json={"recipients": sel, "channel": "telegram", "max_attempts": 3}).json()
    assert pv["eligible"] == 1 and pv["no_contact"] == 1


def test_empty_selection_rejected_and_legacy_campaign_means_everyone(client, auth):
    base = {"name": "R", "channel": "email", "interval_hours": 1, "max_attempts": 2, "batch_size": 10}
    assert client.post("/api/campaigns", headers=auth, json={**base, "recipients": {}}).status_code == 422
    assert client.post("/api/campaigns", headers=auth, json={**base, "recipients": {"batches": []}}).status_code == 422
    cid = client.post("/api/campaigns", headers=auth, json=base).json()["id"]          # no 'recipients' key = old behaviour
    camp = next(c for c in client.get("/api/campaigns", headers=auth).json()["items"] if c["id"] == cid)
    assert camp["recipients"]["legacy"] is True and camp["recipient_total"] >= 55


def test_worker_contacts_only_selected_recipients(client, auth):
    b = next(i["id"] for i in client.get("/api/recipients/options", headers=auth).json()["imports"] if i["filename"] == "fileB.xlsx")
    cid = client.post("/api/campaigns", headers=auth, json={
        "name": "File B only", "channel": "email", "interval_hours": 1, "max_attempts": 3, "batch_size": 500,
        "recipients": {"import_ids": [b]}}).json()["id"]
    client.post(f"/api/campaigns/{cid}/start", headers=auth)
    res = client.post(f"/api/campaigns/{cid}/run-now", headers=auth).json()
    logs = client.get(f"/api/reminders?campaign_id={cid}", headers=auth).json()["items"]
    # file B = PRN 3 and 4, both still pending and subscribed; nobody else in the system is contacted
    assert {l["prn"] for l in logs} == {"31000003", "31000004"}
    assert res["simulated"] == 2 and res["remaining"] == 0


def test_selection_survives_pause_resume_and_edit_without_recipients(client, auth):
    cid = client.post("/api/campaigns", headers=auth, json={
        "name": "Batch 2032", "channel": "email", "interval_hours": 1, "max_attempts": 3, "batch_size": 5,
        "recipients": {"batches": [2032]}}).json()["id"]
    client.post(f"/api/campaigns/{cid}/start", headers=auth)
    client.post(f"/api/campaigns/{cid}/pause", headers=auth)
    client.post(f"/api/campaigns/{cid}/resume", headers=auth)
    # an edit that omits 'recipients' must not wipe the saved audience
    r = client.put(f"/api/campaigns/{cid}", headers=auth, json={
        "name": "Batch 2032 (renamed)", "channel": "email", "interval_hours": 2, "max_attempts": 3, "batch_size": 5})
    assert r.status_code == 200
    camp = next(c for c in client.get("/api/campaigns", headers=auth).json()["items"] if c["id"] == cid)
    assert camp["recipients"]["batches"] == [2032] and camp["recipient_total"] == 2
    # and a real change is saved
    client.put(f"/api/campaigns/{cid}", headers=auth, json={
        "name": "x", "channel": "email", "interval_hours": 2, "max_attempts": 3, "batch_size": 5, "recipients": {"batches": [2031]}})
    camp = next(c for c in client.get("/api/campaigns", headers=auth).json()["items"] if c["id"] == cid)
    assert camp["recipients"]["batches"] == [2031]


def test_deleting_an_alumnus_removes_them_from_file_history(client, auth):
    opts = client.get("/api/recipients/options", headers=auth).json()
    a = next(i for i in opts["imports"] if i["filename"] == "fileA.xlsx")
    before = a["total"]
    client.delete(f"/api/alumni/{_alumnus(client, auth, 31000001)['id']}", headers=auth)
    after = next(i for i in client.get("/api/recipients/options", headers=auth).json()["imports"] if i["id"] == a["id"])["total"]
    assert after == before - 1
