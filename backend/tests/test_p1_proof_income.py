"""Phase 1: proof upload, income range, the review workflow, and keeping all of it private."""
import itertools
import json
import os
import time

import pytest

from app import config, income, ratelimit, storage
from app.db import db

PDF = b"%PDF-1.4\n%joining mail\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 30
EMP = {"company": "Acme", "designation": "Engineer", "industry": "IT"}


@pytest.fixture
def strict(monkeypatch):
    """Switch the Phase 1 requirements on (the legacy tests run with them off)."""
    monkeypatch.setattr(config, "REQUIRE_PROOF", True)
    monkeypatch.setattr(config, "REQUIRE_INCOME_RANGE", True)


_PRN = itertools.count(44000001)      # module level: every test gets a person nobody else has touched


@pytest.fixture
def person(client, auth, import_people):
    def make():
        n = next(_PRN)
        aid = list(import_people([(f"Sample Person{n}", n)], year=2043).values())[0]
        tok = client.get(f"/api/alumni/{aid}", headers=auth).json()["link"].split("token=")[1]
        return aid, tok
    return make


def upload(client, tok, doc_type="JOINING_MAIL", career="EMPLOYMENT", name="mail.pdf", data=PDF, ctype="application/pdf"):
    return client.post("/api/public/proof", data={"token": tok, "career_status": career, "doc_type": doc_type},
                       files={"file": (name, data, ctype)})


def submit(client, tok, career="EMPLOYMENT", details=EMP, band="EMP_5_8", consent=True):
    body = {"token": tok, "career_status": career, "details": details, "consent": consent}
    if band:
        body["income_band"] = band
    return client.post("/api/public/submit", json=body)


def key_of(doc_id):
    with db() as c:
        return c.execute("SELECT storage_key k FROM verification_documents WHERE id=?", (doc_id,)).fetchone()["k"]


# ---------------------------------------------------------------- the form
def test_form_tells_the_page_what_to_ask(client, person):
    _, tok = person()
    f = client.get(f"/api/public/form?token={tok}").json()
    assert set(f["income_bands"]) == {"EMPLOYMENT", "HIGHER_STUDIES", "ENTREPRENEURSHIP"}
    assert [t["code"] for t in f["proof_types"]["EMPLOYMENT"]][:2] == ["JOINING_MAIL", "OFFICE_ID_CARD"]
    assert f["proof"] is None and f["max_upload_mb"] == 5 and "key" not in json.dumps(f).lower().replace("keyword", "")


def test_every_career_type_has_a_valid_way_to_say_nothing_yet():
    for cat, code in (("HIGHER_STUDIES", "HS_NONE"), ("ENTREPRENEURSHIP", "ENT_NONE")):
        assert income.valid(cat, code)
    assert not income.valid("EMPLOYMENT", "HS_NONE") and not income.valid("NOPE", "EMP_LT3")


# ---------------------------------------------------------------- required when switched on
def test_submission_needs_income_consent_and_proof(client, auth, person, strict):
    aid, tok = person()
    assert submit(client, tok, band=None).status_code == 422                           # no income range
    assert submit(client, tok, consent=False).status_code == 422                       # no consent
    r = submit(client, tok)
    assert r.status_code == 422 and "upload a proof" in r.json()["detail"]             # no proof yet
    assert upload(client, tok).status_code == 200
    assert submit(client, tok).status_code == 200
    a = client.get(f"/api/alumni/{aid}", headers=auth).json()
    assert a["income_band"] == "EMP_5_8" and a["income_label"] == "₹5 – 8 LPA" and a["verification_consent_at"]
    assert a["proof"]["status"] == "PENDING" and a["proof"]["doc_label"].startswith("Joining")


@pytest.mark.parametrize("career,details,band,doc", [
    ("HIGHER_STUDIES", {"university": "MIT", "country": "USA", "degree": "MS", "specialization": "AI"}, "HS_NONE", "ADMISSION_LETTER"),
    ("ENTREPRENEURSHIP", {"startup_name": "S", "business_domain": "D", "stage": "Idea"}, "ENT_NONE", "STARTUP_REGISTRATION")])
def test_other_career_types_work_the_same_way(client, person, strict, career, details, band, doc):
    _, tok = person()
    assert upload(client, tok, doc, career).status_code == 200
    assert submit(client, tok, career, details, band).status_code == 200


def test_proof_for_a_different_career_type_is_not_accepted(client, person, strict):
    _, tok = person()
    upload(client, tok, "JOINING_MAIL", "EMPLOYMENT")
    r = submit(client, tok, "HIGHER_STUDIES", {"university": "U", "country": "C", "degree": "D", "specialization": "S"}, "HS_LT1")
    assert r.status_code == 422 and "different option" in r.json()["detail"]


def test_a_wrong_band_is_rejected_even_when_not_required(client, person):
    _, tok = person()
    assert submit(client, tok, band="HS_NONE").status_code == 422                      # a study band on a job
    assert submit(client, tok, band="EMP_5_8", consent=False).status_code == 422       # income is never stored without consent
    assert submit(client, tok, band="EMP_5_8", consent=True).status_code == 200        # optional when not required, valid when given


def test_requirements_off_keeps_the_old_form_working(client, person):
    _, tok = person()
    assert submit(client, tok, band=None, consent=False).status_code == 200


def test_resubmitting_without_an_income_keeps_the_old_one(client, auth, person):
    aid, tok = person()
    submit(client, tok, band="EMP_8_12")
    submit(client, tok, band=None, consent=False)
    assert client.get(f"/api/alumni/{aid}", headers=auth).json()["income_band"] == "EMP_8_12"


# ---------------------------------------------------------------- upload rules
def test_bad_uploads_are_refused_with_a_clear_message(client, person, monkeypatch):
    _, tok = person()
    assert upload(client, tok, name="x.exe").status_code == 422
    assert upload(client, tok, name="x.pdf", data=PNG, ctype="application/pdf").status_code == 422     # content is not a PDF
    assert upload(client, tok, name="x.pdf", data=b"").status_code == 422
    assert upload(client, tok, name="x.pdf", data=b"<?php echo 1;", ctype="application/pdf").status_code == 422
    assert upload(client, tok, doc_type="STARTUP_REGISTRATION").status_code == 422               # not valid for a job
    assert upload(client, tok, career="WIZARD").status_code == 422
    monkeypatch.setattr(config, "MAX_DOCUMENT_BYTES", 100)
    r = upload(client, tok, data=b"%PDF-" + b"0" * 500)
    assert r.status_code == 422 and "too large" in r.json()["detail"]


def test_upload_needs_a_live_link(client, auth, person):
    aid, tok = person()
    assert upload(client, "z" * 30).status_code == 404
    client.post(f"/api/alumni/{aid}/link/revoke", headers=auth)
    assert upload(client, tok).status_code == 410


def test_uploads_are_rate_limited(client, person, monkeypatch):
    _, tok = person()
    monkeypatch.setitem(ratelimit.LIMITS, "public_write", (2, 60))
    assert upload(client, tok).status_code == 200 and upload(client, tok).status_code == 200
    assert upload(client, tok).status_code == 429


def test_a_new_upload_replaces_the_pending_one_and_deletes_its_file(client, auth, person):
    aid, tok = person()
    first = upload(client, tok).json()["proof"]["id"]
    k1 = key_of(first)
    second = upload(client, tok, "OFFICE_ID_CARD", name="id.png", data=PNG, ctype="image/png").json()["proof"]
    assert not storage.get_storage().exists(k1) and storage.get_storage().exists(key_of(second["id"]))
    docs = client.get(f"/api/alumni/{aid}", headers=auth).json()["documents"]
    assert [d["superseded"] for d in docs] == [False, True]
    assert client.post(f"/api/documents/{first}/review", headers=auth, json={"decision": "APPROVED"}).status_code == 409


def test_an_approved_proof_is_kept_when_a_newer_one_arrives(client, auth, person):
    aid, tok = person()
    old = upload(client, tok).json()["proof"]["id"]
    client.post(f"/api/documents/{old}/review", headers=auth, json={"decision": "APPROVED"})
    new = upload(client, tok, "OFFICE_ID_CARD", name="id.png", data=PNG, ctype="image/png").json()["proof"]
    assert storage.get_storage().exists(key_of(old)) and new["status"] == "PENDING" and new["id"] != old


def test_the_number_of_documents_is_capped(client, auth, person, monkeypatch):
    aid, tok = person()
    monkeypatch.setattr(config, "MAX_PROOFS_PER_ALUMNI", 2)
    for _ in range(2):
        d = upload(client, tok).json()["proof"]["id"]
        client.post(f"/api/documents/{d}/review", headers=auth, json={"decision": "APPROVED"})
    assert upload(client, tok).status_code == 409


# ---------------------------------------------------------------- review workflow
def test_rejection_needs_a_reason_and_the_person_sees_it(client, auth, person, strict):
    aid, tok = person()
    doc = upload(client, tok).json()["proof"]["id"]
    assert client.post(f"/api/documents/{doc}/review", headers=auth, json={"decision": "REJECTED"}).status_code == 422
    assert client.post(f"/api/documents/{doc}/review", headers=auth, json={"decision": "REJECTED", "reason": "abc"}).status_code == 422
    assert client.post(f"/api/documents/{doc}/review", headers=auth, json={"decision": "MAYBE"}).status_code == 422
    assert client.post(f"/api/documents/{doc}/review", headers=auth, json={"decision": "REJECTED", "reason": "The ID card is blurred"}).status_code == 200
    f = client.get(f"/api/public/form?token={tok}").json()
    assert f["proof"]["status"] == "REJECTED" and f["proof"]["rejection_reason"] == "The ID card is blurred"
    r = submit(client, tok)
    assert r.status_code == 422 and "blurred" in r.json()["detail"]                      # cannot submit on a rejected proof
    assert upload(client, tok).status_code == 200 and submit(client, tok).status_code == 200


def test_approving_clears_an_old_rejection_reason(client, auth, person):
    _, tok = person()
    doc = upload(client, tok).json()["proof"]["id"]
    client.post(f"/api/documents/{doc}/review", headers=auth, json={"decision": "REJECTED", "reason": "Not readable at all"})
    client.post(f"/api/documents/{doc}/review", headers=auth, json={"decision": "APPROVED"})
    p = client.get(f"/api/public/form?token={tok}").json()["proof"]
    assert p["status"] == "APPROVED" and p["rejection_reason"] is None


def test_queue_filters_and_counts(client, auth, person):
    _, t1 = person()
    _, t2 = person()
    d1 = upload(client, t1).json()["proof"]["id"]
    upload(client, t2, "ADMISSION_LETTER", "HIGHER_STUDIES")
    client.post(f"/api/documents/{d1}/review", headers=auth, json={"decision": "APPROVED"})
    q = client.get("/api/verification?status=PENDING&category=HIGHER_STUDIES", headers=auth).json()
    assert q["total"] >= 1 and all(i["status"] == "PENDING" and i["category"] == "HIGHER_STUDIES" for i in q["items"])
    assert {"PENDING", "APPROVED", "REJECTED"} == set(q["counts"]) and q["counts"]["APPROVED"] >= 1
    assert client.get("/api/verification?status=BOGUS", headers=auth).status_code == 422


def test_only_reviewers_may_review_or_see_the_queue(client, auth, account, person):
    aid, tok = person()
    doc = upload(client, tok).json()["proof"]["id"]
    stu = account("STUDENT")
    assert client.get("/api/verification", headers=stu.headers).status_code == 403
    assert client.post(f"/api/documents/{doc}/review", headers=stu.headers, json={"decision": "APPROVED"}).status_code == 403
    fac = account("FACULTY")
    assert client.post(f"/api/documents/{doc}/review", headers=fac.headers, json={"decision": "APPROVED"}).status_code == 200
    assert client.get(f"/api/alumni/{aid}", headers=fac.headers).json()["documents"][0]["reviewed_by"] == fac.email


def test_review_and_download_are_audited(client, auth, person):
    aid, tok = person()
    doc = upload(client, tok).json()["proof"]["id"]
    client.post(f"/api/documents/{doc}/review", headers=auth, json={"decision": "REJECTED", "reason": "Wrong person's card"})
    client.get(f"/api/documents/{doc}/download", headers=auth)
    acts = {i["action"]: i for i in client.get("/api/audit-logs", headers=auth, params={"entity_id": aid, "page_size": 50}).json()["items"]}
    assert acts["document.review"]["detail"]["to"] == "REJECTED" and "document.download" in acts and "document.upload" in acts


# ---------------------------------------------------------------- download + privacy
def test_download_headers_and_access(client, auth, account, import_people, person):
    aid, tok = person()
    doc = upload(client, tok).json()["proof"]["id"]
    r = client.get(f"/api/documents/{doc}/download", headers=auth)
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert "attachment" in r.headers["content-disposition"]
    owner = account("ALUMNI", aid)
    assert client.get(f"/api/documents/{doc}/download", headers=owner.headers).content == PDF
    other = account("ALUMNI", list(import_people([("Not Owner", 44900001)], year=2043).values())[0])
    assert client.get(f"/api/documents/{doc}/download", headers=other.headers).status_code == 404
    assert client.get(f"/api/documents/{doc}/download", headers=account("STUDENT").headers).status_code == 404
    assert client.get(f"/api/documents/{doc}/download").status_code == 401
    assert client.get("/api/documents/99999999/download", headers=auth).status_code == 404


def test_owner_sees_own_documents_without_staff_fields(client, account, person):
    aid, tok = person()
    upload(client, tok)
    owner = account("ALUMNI", aid)
    item = client.get("/api/profile/me/documents", headers=owner.headers).json()["items"][0]
    assert item["status"] == "PENDING" and "reviewed_by" not in item and "sha256" not in item


def test_file_keys_never_appear_in_any_response(client, auth, account, person):
    aid, tok = person()
    doc = upload(client, tok).json()["proof"]["id"]
    key = key_of(doc)
    bodies = [client.get(f"/api/alumni/{aid}", headers=auth).text, client.get("/api/verification?status=all", headers=auth).text,
              client.get(f"/api/public/form?token={tok}").text, client.get("/api/alumni?page_size=100", headers=auth).text,
              client.get("/api/profile/me/documents", headers=account("ALUMNI", aid).headers).text]
    assert not any(key in b or key[:12] in b for b in bodies)


def test_income_and_proof_never_reach_other_members(client, auth, account, import_people, person):
    aid, tok = person()
    submit(client, tok, band="EMP_20_35")
    upload(client, tok)
    owner = account("ALUMNI", aid)
    client.put("/api/profile/me/visibility", headers=owner.headers, json={"level": "PUBLIC"})
    for headers in ({}, account("STUDENT").headers):
        shown = client.get(f"/api/profiles/{aid}", headers=headers)
        assert set(shown.json()) == {"id", "name", "graduation_year", "career_status", "organisations", "profile", "timeline", "viewer"}   # exactly the allow-list
        text = shown.text.lower()
        for leak in ("income", "emp_20_35", "35 lpa", "proof", "document", "joining"):
            assert leak not in text, leak
    mine = client.get("/api/profile/me", headers=owner.headers).json()
    assert mine["income_band"] == "EMP_20_35"                                     # the owner can see their own


# ---------------------------------------------------------------- lifecycle of the files
def test_deleting_a_person_removes_their_files(client, auth, person):
    aid, tok = person()
    k = key_of(upload(client, tok).json()["proof"]["id"])
    assert storage.get_storage().exists(k)
    assert client.delete(f"/api/alumni/{aid}", headers=auth).status_code == 200
    assert not storage.get_storage().exists(k)
    with db() as c:
        assert c.execute("SELECT COUNT(*) n FROM verification_documents WHERE alumni_id=?", (aid,)).fetchone()["n"] == 0


def test_orphan_sweep_removes_only_old_unreferenced_files(person, client):
    from app import documents
    store = storage.get_storage()
    aid, tok = person()
    kept = key_of(upload(client, tok).json()["proof"]["id"])
    old, fresh = store.save_upload("o.pdf", PDF), store.save_upload("f.pdf", PDF)
    past = time.time() - 3600
    os.utime(store.root / old.key, (past, past))
    os.utime(store.root / kept, (past, past))                    # referenced: must survive even if old
    with db() as c:
        assert documents.sweep_orphans(c, store, grace_seconds=600) == 1
    assert not store.exists(old.key) and store.exists(fresh.key) and store.exists(kept)
    store.delete(fresh.key)


def test_submissions_export_includes_income_and_proof_status(client, auth, person):
    aid, tok = person()
    submit(client, tok, band="EMP_3_5")
    upload(client, tok)
    text = client.get("/api/reports/export?scope=submissions&format=csv", headers=auth).content.decode("utf-8-sig")
    assert text.splitlines()[0].endswith("Income Range,Proof Status") and "₹3 – 5 LPA,PENDING" in text
