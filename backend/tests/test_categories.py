"""Three record categories: placement, higher studies, entrepreneurship.
Self-cleaning: every alumnus these tests add is deleted again, so other test files see the same data."""
import io
from pathlib import Path

import openpyxl
import pytest

from app import importer

DATA = Path(__file__).resolve().parent.parent / "data"
HS_REF = DATA / "reference_higher_studies.xlsx"
ENT_REF = DATA / "reference_entrepreneurship.xlsx"
PL_REF = DATA / "reference_placement.xlsx"

COMMON = ["Sr. No.", "Name of the Student", "PRN No.", "Class and Div", "Contact No", "Email-Id"]
HS_HDR = COMMON + ["Higer Education Degree Name", "College/University Address", "Appointment letter PDF Link"]
ENT_HDR = COMMON + ["Name of the Company", "Registration No.", "Official Website", "Registration letter PDF Link"]


def sheet(header, rows, ay="AY: 2025-26"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([ay])
    ws.append(header)
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def person(n, name="Test Person", prn=41000001):
    return [n, name, prn, "BTech", "9876543210", "tp@example.com"]


def _find(client, auth, prn):
    return client.get(f"/api/alumni?search={prn}", headers=auth).json()["items"]


@pytest.fixture
def cleanup(client, auth):
    prns = []
    yield prns
    for prn in prns:
        for a in _find(client, auth, prn):
            client.delete(f"/api/alumni/{a['id']}", headers=auth)


# ------------------------------------------------------------------ importer (no database)
def test_formats_use_the_exact_reference_headers():
    f = {x["category"]: x for x in importer.formats()}
    assert list(f) == ["PLACEMENT", "HIGHER_STUDIES", "ENTREPRENEURSHIP"]
    assert f["HIGHER_STUDIES"]["columns"][6:] == ["Higer Education Degree Name", "College/University Address", "Appointment letter PDF Link"]
    assert f["ENTREPRENEURSHIP"]["columns"][6:] == ["Name of the Company", "Registration No.", "Official Website", "Registration letter PDF Link"]


@pytest.mark.parametrize("path,cat,n", [(PL_REF, "PLACEMENT", 51), (HS_REF, "HIGHER_STUDIES", 1), (ENT_REF, "ENTREPRENEURSHIP", 1)])
def test_each_reference_sheet_is_detected_and_valid(path, cat, n):
    rep = importer.parse(path.name, path.read_bytes())
    assert rep["ok"], rep["errors"][:3]
    assert rep["category"] == cat and rep["detected"] and rep["summary"]["unique_students"] == n
    assert rep["graduation_year"] == 2026 and not rep["missing_columns"]


def test_blank_numbered_rows_are_ignored():
    rep = importer.parse("h.xlsx", HS_REF.read_bytes())       # the sheet has rows 2..20 holding only a Sr. No.
    assert rep["total_rows"] == 1


def test_real_values_are_read_correctly():
    h = importer.parse("h.xlsx", HS_REF.read_bytes())["students"][0]
    assert (h["prn"], h["phone"]) == ("12210901", "9922269860")
    assert h["higher_studies"] == [{"degree": "MBA", "institution": "Indian Institute of Management - Kozhikode", "letter_link": None}]
    e = importer.parse("e.xlsx", ENT_REF.read_bytes())["students"][0]
    assert e["ventures"][0]["registration_no"] == "U62013PN2023OPC220210"
    assert e["ventures"][0]["website"] == "https://www.praisearray.com/"


def test_correct_spelling_of_degree_header_is_accepted():
    hdr = list(HS_HDR)
    hdr[6] = "Higher Education Degree Name"
    rep = importer.parse("h.xlsx", sheet(hdr, [person(1) + ["MS", "MIT, USA", None]]))
    assert rep["ok"] and rep["category"] == "HIGHER_STUDIES"


def test_forcing_the_wrong_category_reports_missing_columns():
    rep = importer.parse("p.xlsx", PL_REF.read_bytes(), category="HIGHER_STUDIES")
    assert not rep["ok"] and "Higer Education Degree Name" in rep["missing_columns"]


def test_unrecognised_columns_give_a_clear_error():
    rep = importer.parse("x.xlsx", sheet(COMMON + ["Something Else"], [person(1) + ["x"]]))
    assert not rep["ok"] and rep["category"] is None and "Could not tell which record type" in rep["errors"][0]["message"]


def test_prn_accepts_8_or_12_digits_only():
    rows = [person(1, prn=12345678) + ["MS", "MIT", None], person(2, prn=123456789012) + ["MS", "MIT", None],
            person(3, prn=123456789) + ["MS", "MIT", None]]
    rep = importer.parse("h.xlsx", sheet(HS_HDR, rows))
    assert rep["summary"]["valid_rows"] == 2
    assert [e["row"] for e in rep["errors"]] == [5] and "8 or 12 digits" in rep["errors"][0]["message"]


def test_required_fields_and_link_safety():
    rows = [person(1, prn=41000001) + ["", "MIT", None],                       # degree missing
            person(2, prn=41000002) + ["MS", "MIT", "javascript:alert(1)"]]    # unsafe link must never be stored
    rep = importer.parse("h.xlsx", sheet(HS_HDR, rows))
    assert [e["column"] for e in rep["errors"]] == ["Higer Education Degree Name"]
    assert rep["students"][0]["higher_studies"][0]["letter_link"] is None
    ent = importer.parse("e.xlsx", sheet(ENT_HDR, [person(1) + ["Acme Pvt Ltd", "", "www.acme.in", None],
                                                  person(2, prn=41000002) + ["Beta LLP", "REG1", "javascript:x", None]]))
    assert [e["column"] for e in ent["errors"]] == ["Registration No."]
    assert ent["students"][0]["ventures"][0]["website"] is None and any("not a web address" in w["message"] for w in ent["warnings"])


def test_bare_domain_gets_https():
    rep = importer.parse("e.xlsx", sheet(ENT_HDR, [person(1) + ["Acme", "REG1", "www.acme.in", None]]))
    assert rep["students"][0]["ventures"][0]["website"] == "https://www.acme.in"


def test_templates_round_trip_for_every_category():
    for cat in importer.CATEGORY_ORDER:
        rep = importer.parse("t.xlsx", importer.template_workbook(cat))
        assert rep["ok"] and rep["category"] == cat, (cat, rep["errors"][:2])


# ------------------------------------------------------------------ through the API
def test_formats_and_templates_endpoints(client, auth):
    assert len(client.get("/api/import/formats", headers=auth).json()["formats"]) == 3
    for cat in importer.CATEGORY_ORDER:
        r = client.get(f"/api/import/template?category={cat}", headers=auth)
        assert r.status_code == 200 and len(r.content) > 500
    assert client.get("/api/import/template?category=NOPE", headers=auth).status_code == 422


def test_import_all_three_files_into_one_directory(client, auth, cleanup):
    cleanup += ["12210901", "12211260"]
    before = client.get("/api/alumni", headers=auth).json()["category_counts"]
    v = client.post("/api/import/validate", headers=auth, files={"file": ("h.xlsx", HS_REF.read_bytes())}).json()
    assert v["ok"] and v["category"] == "HIGHER_STUDIES" and v["already_in_database"] == 0
    h = client.post("/api/import", headers=auth, files={"file": ("h.xlsx", HS_REF.read_bytes())}).json()
    e = client.post("/api/import", headers=auth, files={"file": ("e.xlsx", ENT_REF.read_bytes())}).json()
    assert (h["added"], h["higher_studies_added"], h["category"]) == (1, 1, "HIGHER_STUDIES")
    assert (e["added"], e["ventures_added"], e["category"]) == (1, 1, "ENTREPRENEURSHIP")

    after = client.get("/api/alumni", headers=auth).json()["category_counts"]
    assert after["all"] == before["all"] + 2
    assert (after["HIGHER_STUDIES"], after["ENTREPRENEURSHIP"]) == (before["HIGHER_STUDIES"] + 1, before["ENTREPRENEURSHIP"] + 1)

    only_hs = client.get("/api/alumni?category=HIGHER_STUDIES", headers=auth).json()
    assert only_hs["total"] == 1 and only_hs["items"][0]["higher_studies"][0]["degree"] == "MBA"
    assert only_hs["items"][0]["categories"] == ["HIGHER_STUDIES"]
    only_ent = client.get("/api/alumni?category=ENTREPRENEURSHIP", headers=auth).json()
    assert only_ent["items"][0]["ventures"][0]["company"].startswith("PRAISEARRAY")
    assert client.get("/api/alumni?category=bogus", headers=auth).status_code == 422
    # search reaches the new fields
    assert client.get("/api/alumni?search=Kozhikode", headers=auth).json()["total"] == 1
    assert client.get("/api/alumni?search=praisearray", headers=auth).json()["total"] == 1
    # the import history remembers each file's category (campaign audience picker shows it)
    imports = {i["id"]: i for i in client.get("/api/recipients/options", headers=auth).json()["imports"]}
    assert imports[h["import_id"]]["category"] == "HIGHER_STUDIES"


def test_merge_same_student_across_categories(client, auth, cleanup):
    cleanup.append("41000009")
    p = person(1, "Multi Cat", 41000009)
    client.post("/api/import", headers=auth, files={"file": ("p.xlsx", sheet(
        importer.headers("PLACEMENT"), [p + ["Acme", 7.0, "SDE", None, None]]))})
    client.post("/api/import", headers=auth, files={"file": ("h.xlsx", sheet(HS_HDR, [p + ["MS", "MIT, USA", None]]))})
    items = _find(client, auth, 41000009)
    assert len(items) == 1                                   # merged by PRN, not duplicated
    assert items[0]["categories"] == ["PLACEMENT", "HIGHER_STUDIES"]
    assert len(items[0]["offers"]) == 1 and len(items[0]["higher_studies"]) == 1
    # re-importing the same file changes nothing
    again = client.post("/api/import", headers=auth, files={"file": ("h.xlsx", sheet(HS_HDR, [p + ["MS", "MIT, USA", None]]))}).json()
    assert again["higher_studies_added"] == 0 and len(_find(client, auth, 41000009)[0]["higher_studies"]) == 1


def test_wrong_category_forced_is_rejected(client, auth):
    r = client.post("/api/import", headers=auth, data={"category": "ENTREPRENEURSHIP"}, files={"file": ("p.xlsx", PL_REF.read_bytes())})
    assert r.status_code == 422 and r.json()["detail"]["report"]["missing_columns"]


def test_exports_for_each_category_reimport_cleanly(client, auth, cleanup):
    cleanup += ["12210901", "12211260"]
    client.post("/api/import", headers=auth, files={"file": ("h.xlsx", HS_REF.read_bytes())})
    client.post("/api/import", headers=auth, files={"file": ("e.xlsx", ENT_REF.read_bytes())})
    for scope, cat, n in (("placement", "PLACEMENT", 51), ("higher_studies", "HIGHER_STUDIES", 1), ("entrepreneurship", "ENTREPRENEURSHIP", 1)):
        for fmt in ("csv", "xlsx"):
            r = client.get(f"/api/reports/export?scope={scope}&format={fmt}", headers=auth)
            assert r.status_code == 200 and len(r.content) > 100
        x = client.get(f"/api/reports/export?scope={scope}&format=xlsx", headers=auth)
        rep = client.post("/api/import/validate", headers=auth, data={"graduation_year": "2026"}, files={"file": ("x.xlsx", x.content)}).json()
        assert rep["ok"] and rep["category"] == cat and rep["summary"]["unique_students"] == n, (scope, rep["errors"][:2])
    assert client.get("/api/reports/export?scope=nope&format=csv", headers=auth).status_code == 422


def test_progression_index_matches_the_summary_sheet_formula(client, auth, cleanup):
    cleanup += ["12210901", "12211260"]
    client.post("/api/import", headers=auth, files={"file": ("p.xlsx", PL_REF.read_bytes())})   # sets final-year students = 77
    client.post("/api/import", headers=auth, files={"file": ("h.xlsx", HS_REF.read_bytes())})
    client.post("/api/import", headers=auth, files={"file": ("e.xlsx", ENT_REF.read_bytes())})
    d = client.get("/api/reports/analytics", headers=auth).json()
    p = d["progression"]
    assert (p["placed"], p["higher_studies"], p["entrepreneurship"], p["total"]) == (51, 1, 1, 53)
    assert p["final_year_students"] == 77 and p["index"] == round(100 * 53 / 77, 2)
    assert d["higher_studies"]["top_institutions"][0]["institution"].startswith("Indian Institute of Management")
    assert d["entrepreneurship"]["companies"][0]["founder"] == "BORA TANMAY PRASHANT"


def test_public_form_prefills_from_the_matching_category(client, auth, cleanup):
    cleanup += ["12210901", "12211260"]
    client.post("/api/import", headers=auth, files={"file": ("h.xlsx", HS_REF.read_bytes())})
    client.post("/api/import", headers=auth, files={"file": ("e.xlsx", ENT_REF.read_bytes())})

    def form(prn):
        a = _find(client, auth, prn)[0]
        tok = client.get(f"/api/alumni/{a['id']}", headers=auth).json()["link"].split("token=")[1]
        return client.get(f"/api/public/form?token={tok}").json()["prefill"]
    hs = form("12210901")
    assert hs["kind"] == "HIGHER_STUDIES" and hs["degree"] == "MBA" and "Kozhikode" in hs["university"]
    ent = form("12211260")
    assert ent["kind"] == "ENTREPRENEURSHIP" and ent["startup_name"].startswith("PRAISEARRAY")


def test_delete_and_undo_restore_higher_studies_and_ventures(client, auth, cleanup):
    cleanup += ["12210901", "12211260"]
    client.post("/api/import", headers=auth, files={"file": ("h.xlsx", HS_REF.read_bytes())})
    client.post("/api/import", headers=auth, files={"file": ("e.xlsx", ENT_REF.read_bytes())})
    for prn, key in (("12210901", "higher_studies"), ("12211260", "ventures")):
        a = _find(client, auth, prn)[0]
        assert client.delete(f"/api/alumni/{a['id']}", headers=auth).status_code == 200
        assert client.post("/api/undo", headers=auth).status_code == 200
        back = _find(client, auth, prn)
        assert len(back) == 1 and len(back[0][key]) == 1


def test_reminder_placeholder_works_for_non_placement_alumni(client, auth, cleanup):
    from app import services
    from app.db import db
    cleanup.append("12210901")
    client.post("/api/import", headers=auth, files={"file": ("h.xlsx", HS_REF.read_bytes())})
    with db() as c:
        aid = _find(client, auth, "12210901")[0]["id"]
        assert "Kozhikode" in services._other_org(c, aid)


def test_old_database_is_upgraded(tmp_path, monkeypatch):
    import sqlite3
    from app import config, db
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE import_batches(id INTEGER PRIMARY KEY, filename TEXT NOT NULL, graduation_year INTEGER,"
                      " added INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0, unique_students INTEGER NOT NULL DEFAULT 0,"
                      " created_at TEXT NOT NULL DEFAULT (datetime('now')));"
                      "INSERT INTO import_batches(filename,graduation_year) VALUES('old.xlsx',2025);")
    old.commit(); old.close()
    monkeypatch.setattr(config, "DB_PATH", str(path))
    db.init()
    with db.db() as c:
        assert c.execute("SELECT category FROM import_batches").fetchone()["category"] == "PLACEMENT"   # old files were placement sheets
        assert c.execute("SELECT COUNT(*) n FROM higher_studies").fetchone()["n"] == 0
    db.init()    # idempotent
