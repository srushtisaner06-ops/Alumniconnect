"""Verification proof uploads up to the configured limit (default 1 GB, streamed to disk), no 'screenshot' wording,
and contact details on the alumni form."""
import asyncio
import hashlib
import io
import itertools
import json

import pytest

from app import config, documents, storage
from app.db import db
from app.uploadguard import UploadSizeGuard

MB = 1024 * 1024
EMP = {"company": "Acme", "designation": "Engineer", "industry": "IT"}
_PRN = itertools.count(49000001)


@pytest.fixture
def person(client, auth, import_people):
    def make(year=2091):
        n = next(_PRN)
        aid = list(import_people([(f"Upload Person{n}", n)], year=year).values())[0]
        tok = client.get(f"/api/alumni/{aid}", headers=auth).json()["link"].split("token=")[1]
        return aid, tok
    return make


def pdf(size):
    return b"%PDF-1.4\n" + b"0" * (size - 9)


def upload(client, tok, data, name="proof.pdf", ctype="application/pdf"):
    return client.post("/api/public/proof", data={"token": tok, "career_status": "EMPLOYMENT", "doc_type": "JOINING_MAIL"},
                       files={"file": (name, data, ctype)})


def submit(client, tok, **extra):
    return client.post("/api/public/submit", json={"token": tok, "career_status": "EMPLOYMENT", "details": EMP, "consent": True, **extra})


def stored_files():
    root = storage.get_storage().root
    return sorted(p.name for p in root.iterdir())


# ---------------------------------------------------------------- the limit
def test_default_limit_is_one_gigabyte_and_the_form_reports_it(client, person):
    assert config.MAX_DOCUMENT_BYTES == 1024 * MB
    _, tok = person()
    assert client.get(f"/api/public/form?token={tok}").json()["max_upload_mb"] == 1024


def test_size_labels():
    assert storage.size_label(1024 ** 3) == "1 GB" and storage.size_label(int(1.5 * 1024 ** 3)) == "1.5 GB"
    assert storage.size_label(50 * MB) == "50 MB" and storage.size_label(300 * 1024) == "300 KB" and storage.size_label(10) == "1 KB"
    assert "maximum 1 GB" in str(storage.too_large(1024 ** 3))


def test_a_file_far_over_the_old_5mb_limit_is_stored_and_downloads_intact(client, auth, person):
    aid, tok = person()
    data = pdf(12 * MB + 123)
    r = upload(client, tok, data)
    assert r.status_code == 200, r.text
    proof = r.json()["proof"]
    assert proof["size_bytes"] == len(data) and proof["content_type"] == "application/pdf"
    with db() as c:
        row = c.execute("SELECT * FROM verification_documents WHERE id=?", (proof["id"],)).fetchone()
    assert row["sha256"] == hashlib.sha256(data).hexdigest() and row["size_bytes"] == len(data)
    d = client.get(f"/api/documents/{proof['id']}/download", headers=auth)
    assert d.status_code == 200 and d.content == data
    assert d.headers["content-length"] == str(len(data)) and d.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in d.headers["content-disposition"]
    log = client.get("/api/audit-logs", headers=auth, params={"action": "document.upload", "entity_id": aid}).json()["items"][0]
    assert log["detail"]["bytes"] == len(data)


def test_a_file_over_the_limit_is_refused_and_leaves_nothing_behind(client, person, monkeypatch):
    _, tok = person()
    monkeypatch.setattr(config, "MAX_DOCUMENT_BYTES", 1 * MB)
    before = stored_files()
    r = upload(client, tok, pdf(MB + MB // 2))                               # inside the form overhead, so the route itself refuses it
    assert r.status_code == 422 and "too large (maximum 1 MB)" in r.json()["detail"]
    big = upload(client, tok, pdf(3 * MB))                                   # clearly over: refused by its declared size, body never read
    assert big.status_code == 413 and "too large (maximum 1 MB)" in big.json()["detail"]
    assert stored_files() == before                                          # no finished file and no half-written .part file
    assert upload(client, tok, pdf(1 * MB)).status_code == 200               # exactly at the limit is fine


def test_streaming_storage_directly(tmp_path):
    s = storage.LocalPrivateStorage(tmp_path)
    data = pdf(3 * MB + 7)
    f = s.save_stream("a.pdf", io.BytesIO(data), "application/pdf")
    assert f.size == len(data) and f.sha256 == hashlib.sha256(data).hexdigest() and s.get(f.key) == data
    assert b"".join(s.iter_chunks(f.key)) == data
    for bad_name, bad in (("a.pdf", b"not a pdf at all"), ("a.exe", pdf(100)), ("a.pdf", b"")):
        with pytest.raises(storage.StorageError):
            s.save_stream(bad_name, io.BytesIO(bad))
    with pytest.raises(storage.StorageError, match="too large"):
        s.save_stream("b.pdf", io.BytesIO(pdf(2 * MB)), max_bytes=MB)
    with pytest.raises(storage.StorageError, match="too large"):
        s.save_stream("b.pdf", io.BytesIO(pdf(MB + 1)), max_bytes=MB)        # one byte over, found in the last chunk
    assert sorted(p.name for p in tmp_path.iterdir()) == [f.key]             # only the good file remains


def test_scan_hook_still_applies_to_streamed_files(tmp_path, monkeypatch):
    def refuse(data):
        raise storage.StorageError("Virus found")
    monkeypatch.setattr(storage, "SCAN_HOOK", refuse)
    s = storage.LocalPrivateStorage(tmp_path)
    with pytest.raises(storage.StorageError, match="Virus"):
        s.save_stream("a.pdf", io.BytesIO(pdf(1000)))
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- refusing a huge body before it is read
def _call_guard(method, path, content_length):
    sent, reached = [], []

    async def app(scope, receive, send):
        reached.append(True)

    async def send(msg):
        sent.append(msg)

    guard = UploadSizeGuard(app, {"/api/public/proof"}, lambda: 10 * MB)
    headers = [(b"content-length", str(content_length).encode())] if content_length is not None else []
    asyncio.run(guard({"type": "http", "method": method, "path": path, "headers": headers}, None, send))
    return sent, reached


def test_upload_guard():
    sent, reached = _call_guard("POST", "/api/public/proof", 50 * MB)
    assert not reached and sent[0]["status"] == 413 and "too large" in json.loads(sent[1]["body"])["detail"]
    assert _call_guard("POST", "/api/public/proof", 10 * MB + 1000)[1]                      # form overhead is allowed for
    assert _call_guard("POST", "/api/public/proof", None)[1]                                # no declared size: the route enforces it
    assert _call_guard("POST", "/api/public/submit", 50 * MB)[1]                            # other paths are not touched
    assert _call_guard("GET", "/api/public/proof", 50 * MB)[1]


# ---------------------------------------------------------------- wording
def test_no_screenshot_wording_in_the_verification_section(client, person):
    _, tok = person()
    form = json.dumps(client.get(f"/api/public/form?token={tok}").json()).lower()
    assert "screenshot" not in form and "screenshot" not in json.dumps(documents.for_form()).lower()
    assert documents.type_label("EMPLOYMENT", "JOINING_MAIL") == "Joining or offer-confirmation email"


# ---------------------------------------------------------------- contact details on the form
def _alumnus(auth, client, aid):
    return client.get(f"/api/alumni/{aid}", headers=auth).json()


def test_form_shows_the_current_contact_details(client, person):
    _, tok = person()
    f = client.get(f"/api/public/form?token={tok}").json()
    assert set(f["contact"]) == {"email", "phone"} and f["contact"]["email"] and f["contact"]["phone"]


def test_submitting_corrected_contact_details_updates_the_record(client, auth, person):
    aid, tok = person()
    r = submit(client, tok, email="  New.Address@Example.COM ", phone="+91 98765-43210")
    assert r.status_code == 200, r.text
    a = _alumnus(auth, client, aid)
    assert a["email"] == "new.address@example.com" and a["phone"] == "9876543210"
    assert client.get(f"/api/public/form?token={tok}").json()["contact"] == {"email": "new.address@example.com", "phone": "9876543210"}
    log = [x for x in client.get("/api/audit-logs", headers=auth, params={"action": "public.submit", "entity_id": aid}).json()["items"]][0]
    assert log["detail"]["contact_changed"]["email"][1] == "new.address@example.com" and log["detail"]["contact_changed"]["phone"][1] == "9876543210"
    assert log["detail"]["contact_changed"]["email"][0]                                    # the old value is kept for the audit trail
    again = submit(client, tok, email="new.address@example.com", phone="09876543210")       # same values, different format: no change
    assert again.status_code == 200
    log2 = client.get("/api/audit-logs", headers=auth, params={"action": "public.submit", "entity_id": aid}).json()["items"][0]
    assert "contact_changed" not in log2["detail"]


@pytest.mark.parametrize("phone", ["12345", "5876543210", "98765 4321", "abcdefghij", "+1 415 555 0100"])
def test_bad_phone_numbers_are_refused(client, auth, person, phone):
    aid, tok = person()
    before = _alumnus(auth, client, aid)
    assert submit(client, tok, phone=phone).status_code == 422
    after = _alumnus(auth, client, aid)
    assert after["phone"] == before["phone"] and after["status"] == before["status"] == "PENDING"


@pytest.mark.parametrize("email", ["nope", "a@b", "a b@c.com", "x" * 200 + "@example.com"])
def test_bad_emails_are_refused(client, auth, person, email):
    aid, tok = person()
    before = _alumnus(auth, client, aid)
    assert submit(client, tok, email=email).status_code == 422
    assert _alumnus(auth, client, aid)["email"] == before["email"]


def test_contact_details_are_optional_for_older_clients(client, auth, person):
    aid, tok = person()
    before = _alumnus(auth, client, aid)
    assert submit(client, tok).status_code == 200
    after = _alumnus(auth, client, aid)
    assert (after["email"], after["phone"]) == (before["email"], before["phone"]) and after["status"] == "COMPLETED"
