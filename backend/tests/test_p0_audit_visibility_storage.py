"""Phase 0: audit trail, profile visibility, private document storage, migrations."""
import sqlite3

import pytest

from app import audit, config, db as dbmod, storage, visibility
from app.db import db

PDF = b"%PDF-1.4\n%fake\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPG = b"\xff\xd8\xff\xe0" + b"0" * 20


def logs(client, auth, **q):
    return client.get("/api/audit-logs", headers=auth, params=q).json()


# ---------------------------------------------------------------- audit
def test_actions_are_audited_with_actor_and_ip(client, auth, import_people):
    aid = list(import_people([("Audit Person", 43000001)]).values())[0]
    client.patch(f"/api/alumni/{aid}", headers=auth, json={"unsubscribed": True})
    client.get(f"/api/alumni/{aid}", headers=auth)
    client.get("/api/reports/export?scope=placement&format=csv", headers=auth)
    client.delete(f"/api/alumni/{aid}", headers=auth)
    items = logs(client, auth, entity_type="alumni", entity_id=aid)["items"]
    actions = {i["action"] for i in items}
    assert {"alumni.update", "alumni.view", "alumni.delete"} <= actions
    row = next(i for i in items if i["action"] == "alumni.delete")
    assert row["actor_email"] == "admin@vit.edu" and row["actor_role"] == "ADMIN" and row["ip"]
    assert any(i["action"] == "export.run" for i in logs(client, auth, action="export")["items"])


def test_failed_login_is_recorded_and_committed(client, auth):
    client.post("/api/auth/login", json={"email": "audit-ghost@example.com", "password": "hunter2-secret"})
    row = logs(client, auth, action="auth.login", outcome="FAILED", actor="audit-ghost")["items"][0]
    assert row["detail"]["reason"] == "unknown"
    assert "hunter2" not in str(row)


def test_secrets_never_reach_the_log(client, auth, account):
    u = account("FACULTY")
    client.post("/api/auth/change-password", headers=u.headers, json={"current_password": u.password, "new_password": "Zx9-Another-Pw"})
    dump = str(logs(client, auth, page_size=200))
    assert u.password not in dump and "Zx9-Another-Pw" not in dump and u.token not in dump
    assert audit._clean({"password": "p", "api_token": "t", "ok": 1, "nested": {"Authorization": "x"}}) == \
        {"password": "[redacted]", "api_token": "[redacted]", "ok": 1, "nested": {"Authorization": "[redacted]"}}


def test_audit_log_is_append_only():
    with db() as c:
        audit.record(c, "test.row")
    for sql in ("UPDATE audit_logs SET action='x'", "DELETE FROM audit_logs"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            with db() as c:
                c.execute(sql)


def test_only_admin_reads_the_audit_log_and_it_filters(client, auth, account):
    assert client.get("/api/audit-logs", headers=account("FACULTY").headers).status_code == 403
    r = logs(client, auth, action="user.", page_size=5)
    assert r["total"] >= 1 and all(i["action"].startswith("user.") for i in r["items"])
    assert logs(client, auth, since="2999-01-01")["total"] == 0


def test_public_submission_is_audited(client, auth, import_people):
    aid = list(import_people([("Public Person", 43000002)]).values())[0]
    tok = client.get(f"/api/alumni/{aid}", headers=auth).json()["link"].split("token=")[1]
    r = client.post("/api/public/submit", json={"token": tok, "career_status": "EMPLOYMENT",
                                                 "details": {"company": "A", "designation": "B", "industry": "C"}})
    assert r.status_code == 200
    row = logs(client, auth, action="public.submit", entity_id=aid)["items"][0]
    assert row["detail"] == {"career_status": "EMPLOYMENT", "resubmission": False} and "token" not in str(row)


# ---------------------------------------------------------------- visibility
def _setup(client, auth, account, import_people, prn):
    ids = import_people([("Vis Owner", prn), ("Vis Other", prn + 1)])
    owner = account("ALUMNI", ids[prn])
    return ids[prn], owner, account("ALUMNI", ids[prn + 1]), account("STUDENT"), account("FACULTY")


def _get(client, aid, headers=None):
    return client.get(f"/api/profiles/{aid}", headers=headers or {})


def test_default_is_private_to_everyone_but_owner_and_staff(client, auth, account, import_people):
    aid, owner, other, student, fac = _setup(client, auth, account, import_people, 43100001)
    assert client.get("/api/profile/me/visibility", headers=owner.headers).json()["level"] == "PRIVATE"
    assert _get(client, aid).status_code == 404
    assert _get(client, aid, other.headers).status_code == 404
    assert _get(client, aid, student.headers).status_code == 404
    assert _get(client, aid, owner.headers).status_code == 200
    assert _get(client, aid, fac.headers).status_code == 200
    assert _get(client, aid, auth).status_code == 200
    assert _get(client, 99999999, student.headers).status_code == 404            # same answer as a private one


@pytest.mark.parametrize("level,alumni,student,anon", [
    ("ALUMNI_ONLY", 200, 404, 404), ("INSTITUTION", 200, 200, 404), ("PUBLIC", 200, 200, 200), ("PRIVATE", 404, 404, 404)])
def test_each_level_opens_exactly_its_audience(client, auth, account, import_people, level, alumni, student, anon):
    aid, owner, other, stu, _ = _setup(client, auth, account, import_people, 43100010 + visibility.LEVELS.index(level) * 2)
    assert client.put("/api/profile/me/visibility", headers=owner.headers, json={"level": level}).status_code == 200
    assert _get(client, aid, other.headers).status_code == alumni
    assert _get(client, aid, stu.headers).status_code == student
    assert _get(client, aid).status_code == anon


def test_shared_view_never_contains_contact_salary_or_secrets(client, auth, account, import_people):
    aid, owner, other, stu, _ = _setup(client, auth, account, import_people, 43100030)
    client.put("/api/profile/me/visibility", headers=owner.headers, json={"level": "PUBLIC"})
    body = _get(client, aid).json()
    assert set(body) <= set(visibility.SHARED_FIELDS) | {"viewer"} and body["organisations"] == ["Acme Corp"]
    text = str(_get(client, aid, stu.headers).json()).lower()
    for leak in ("43100030", "@example.com", "9876500000", "7.5", "token", "prn", "package", "phone", "email"):
        assert leak not in text, leak


def test_owner_sees_own_data_but_not_internal_fields_or_link(client, auth, account, import_people):
    aid, owner, *_ = _setup(client, auth, account, import_people, 43100040)
    me = client.get("/api/profile/me", headers=owner.headers).json()
    assert me["prn"] == "43100040" and me["viewer"] == "owner"
    assert not {"token", "reminders_sent", "unsubscribed", "token_expires_at"} & set(me)


def test_alumnus_cannot_change_anyone_elses_privacy_and_levels_are_validated(client, auth, account, import_people):
    aid, owner, other, stu, fac = _setup(client, auth, account, import_people, 43100050)
    assert client.put("/api/profile/me/visibility", headers=owner.headers, json={"level": "EVERYONE"}).status_code == 422
    assert client.put("/api/profile/me/visibility", headers=stu.headers, json={"level": "PUBLIC"}).status_code == 403   # students have no profile
    assert client.put("/api/profile/me/visibility", headers=fac.headers, json={"level": "PUBLIC"}).status_code == 403   # staff cannot override
    assert client.put(f"/api/alumni/{aid}/visibility", headers=other.headers, json={"level": "PUBLIC"}).status_code in (404, 405)
    assert _get(client, aid).status_code == 404
    assert client.get(f"/api/alumni/{aid}/visibility", headers=fac.headers).json()["level"] == "PRIVATE"


def test_visibility_changes_are_audited_and_survive_delete_undo(client, auth, account, import_people):
    aid, owner, other, *_ = _setup(client, auth, account, import_people, 43100060)
    client.put("/api/profile/me/visibility", headers=owner.headers, json={"level": "INSTITUTION"})
    assert logs(client, auth, action="profile.visibility", entity_id=aid)["items"][0]["detail"] == {"from": "PRIVATE", "to": "INSTITUTION"}
    client.delete(f"/api/alumni/{aid}", headers=auth)
    client.post("/api/undo", headers=auth)
    with db() as c:
        assert visibility.get_level(c, aid) == "INSTITUTION"


# ---------------------------------------------------------------- storage
@pytest.mark.parametrize("name,data,ctype", [("a.pdf", PDF, "application/pdf"), ("b.PNG", PNG, "image/png"),
                                              ("c.jpg", JPG, "image/jpeg"), ("d.jpeg", JPG, "image/jpeg")])
def test_valid_uploads_pass(name, data, ctype):
    assert storage.validate_upload(name, data)[1] == ctype


@pytest.mark.parametrize("name,data", [
    ("x.exe", PDF), ("x.pdf.exe", PDF), ("x", PDF), ("x.pdf", PNG), ("x.png", PDF),
    ("x.pdf", b""), ("x.pdf", b"<?php system($_GET[1]);")],
    ids=["exe", "double-extension", "no-extension", "pdf-name-png-body", "png-name-pdf-body", "empty", "php-as-pdf"])
def test_bad_uploads_are_rejected(name, data):
    with pytest.raises(storage.StorageError):
        storage.validate_upload(name, data)


def test_oversize_upload_is_rejected():
    # Built inside the test, never as a parameter: pytest copies parameters into an environment variable, and
    # Windows refuses values over 32,767 characters.
    with pytest.raises(storage.StorageError, match="too large"):
        storage.validate_upload("x.pdf", b"%PDF-" + b"0" * config.MAX_DOCUMENT_BYTES)
    storage.validate_upload("x.pdf", b"%PDF-" + b"0" * 100, max_bytes=1000)           # under the limit passes
    with pytest.raises(storage.StorageError, match="too large"):
        storage.validate_upload("x.pdf", b"%PDF-" + b"0" * 100, max_bytes=50)


def test_declared_content_type_must_agree():
    with pytest.raises(storage.StorageError):
        storage.validate_upload("x.pdf", PDF, declared_type="text/html")
    storage.validate_upload("x.pdf", PDF, declared_type="application/octet-stream")


def test_filenames_are_sanitised():
    assert storage.safe_filename("../../etc/passwd") == "passwd"
    assert storage.safe_filename("C:\\evil\\a.pdf") == "a.pdf" and storage.safe_filename("\x00..") == "document"
    assert len(storage.safe_filename("a" * 500 + ".pdf")) == 100


def test_local_storage_roundtrip_and_traversal(tmp_path):
    s = storage.LocalPrivateStorage(tmp_path / "vault")
    f = s.save_upload("../../scan.pdf", PDF, "application/pdf")
    assert f.original_name == "scan.pdf" and f.size == len(PDF) and len(f.sha256) == 64
    assert s.get(f.key) == PDF and s.exists(f.key) and all(p.parent == s.root for p in s.root.iterdir())
    assert f.key != "scan.pdf"                                       # the client never chooses the stored name
    for bad in ("../x.pdf", "..\\x.pdf", "/etc/passwd", "a" * 32, f.key + "/..", f.key.upper(), None):
        with pytest.raises(storage.StorageError):
            s.get(bad)
    with pytest.raises(storage.StorageError):
        s.put(f.key, b"overwrite")                                   # keys are never reused
    s.delete(f.key)
    assert not s.exists(f.key)


def test_scan_hook_can_refuse_a_file(tmp_path, monkeypatch):
    def deny(data):
        raise storage.StorageError("Virus found")
    monkeypatch.setattr(storage, "SCAN_HOOK", deny)
    with pytest.raises(storage.StorageError, match="Virus"):
        storage.LocalPrivateStorage(tmp_path).save_upload("a.pdf", PDF)


# ---------------------------------------------------------------- migrations / production guard
def test_legacy_database_upgrades_without_losing_data(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    old = sqlite3.connect(path)
    old.executescript(dbmod.SCHEMA)                                  # the pre-Phase-0 schema
    old.execute("INSERT INTO users(email,password_hash) VALUES('boss@x.edu','h')")
    old.execute("INSERT INTO alumni(name,prn,graduation_year,token) VALUES('Old Timer','11111111',2020,'t'||hex(randomblob(12)))")
    old.commit(); old.close()
    monkeypatch.setattr(config, "DB_PATH", str(path))
    dbmod.init(); dbmod.init()                                       # twice: idempotent
    with db() as c:
        assert c.execute("SELECT role FROM users").fetchone()["role"] == "ADMIN"
        a = c.execute("SELECT * FROM alumni").fetchone()
        assert a["name"] == "Old Timer" and a["token_expires_at"] and a["token_revoked_at"] is None
        assert [r["version"] for r in c.execute("SELECT version FROM schema_migrations")] == [1]
        assert c.execute("SELECT COUNT(*) n FROM permissions").fetchone()["n"] >= 13


def test_users_created_without_a_role_get_least_privilege(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "x.db"))
    dbmod.init()
    with db() as c:
        c.execute("INSERT INTO users(email,password_hash) VALUES('n@x.edu','h')")
        assert c.execute("SELECT role FROM users").fetchone()["role"] == "STUDENT"


def test_production_refuses_development_defaults(monkeypatch):
    monkeypatch.setattr(config, "SECRET_KEY", config.DEV_SECRET_KEY)
    monkeypatch.setattr(config, "ADMIN_PASSWORD", config.DEV_ADMIN_PASSWORD)
    assert len(config.check_production()) == 2                        # both development defaults are refused
    monkeypatch.setattr(config, "SECRET_KEY", "x" * 40)
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "A-real-password-9")
    monkeypatch.setattr(config, "CORS_ORIGINS", ["https://alumni.example.edu"])
    assert config.check_production() == []
    monkeypatch.setattr(config, "CORS_ORIGINS", ["*"])
    assert any("CORS" in p for p in config.check_production())
