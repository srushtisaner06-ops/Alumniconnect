"""Phase 0: login, sessions, lockout, password rules/reset, and the role/permission boundaries."""
import pytest

from app import accounts, config
from app.db import db

PW = "Str0ng-Pass-1"


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_returns_role_and_permissions(client):
    r = login(client, "admin@vit.edu", "test-pass").json()
    assert r["role"] == "ADMIN" and "user.manage" in r["permissions"] and r["token"]


def test_wrong_password_and_unknown_email_look_identical(client):
    a = login(client, "admin@vit.edu", "nope")
    b = login(client, "nobody@example.com", "nope")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_logout_really_ends_the_session(client, account):
    u = account("FACULTY")
    assert client.get("/api/auth/me", headers=u.headers).status_code == 200
    assert client.post("/api/auth/logout", headers=u.headers).status_code == 200
    assert client.get("/api/auth/me", headers=u.headers).status_code == 401      # the JWT is still well-formed, but its session is dead


def test_lockout_after_repeated_failures_blocks_even_the_right_password(client, account):
    u = account("FACULTY")
    for _ in range(config.LOCKOUT_THRESHOLD):
        assert login(client, u.email, "wrong").status_code == 401
    assert login(client, u.email, u.password).status_code == 401
    with db() as c:                                                              # lock expires
        c.execute("UPDATE users SET locked_until='2000-01-01 00:00:00' WHERE id=?", (u.id,))
    assert login(client, u.email, u.password).status_code == 200


def test_unauthenticated_requests_are_rejected_everywhere(client):
    for method, path in [("get", "/api/alumni"), ("get", "/api/dashboard"), ("get", "/api/users"), ("get", "/api/audit-logs"),
                         ("get", "/api/campaigns"), ("get", "/api/reports/export"), ("post", "/api/import"), ("get", "/api/undo")]:
        assert getattr(client, method)(path).status_code == 401, path


@pytest.mark.parametrize("role,allowed,denied", [
    ("FACULTY", ["/api/alumni", "/api/dashboard", "/api/campaigns", "/api/reports/analytics"], ["/api/users", "/api/audit-logs", "/api/roles"]),
    ("ALUMNI", [], ["/api/alumni", "/api/dashboard", "/api/campaigns", "/api/users", "/api/audit-logs", "/api/reports/export"]),
    ("STUDENT", [], ["/api/alumni", "/api/dashboard", "/api/campaigns", "/api/users", "/api/audit-logs"]),
])
def test_role_boundaries(client, account, import_people, role, allowed, denied):
    ids = import_people([("Role Probe", 41000001 + len(role))])
    u = account(role, alumni_id=list(ids.values())[0] if role == "ALUMNI" else None)
    for p in allowed:
        assert client.get(p, headers=u.headers).status_code == 200, p
    for p in denied:
        assert client.get(p, headers=u.headers).status_code == 403, p


def test_faculty_cannot_delete_or_manage_users_but_admin_can(client, auth, account, import_people):
    aid = list(import_people([("Delete Probe", 41000010)]).values())[0]
    fac = account("FACULTY")
    assert client.delete(f"/api/alumni/{aid}", headers=fac.headers).status_code == 403
    assert client.post("/api/users", headers=fac.headers, json={"email": "x@example.com", "password": PW, "role": "ADMIN"}).status_code == 403
    assert client.delete(f"/api/alumni/{aid}", headers=auth).status_code == 200


def test_role_change_takes_effect_immediately(client, auth, account):
    u = account("FACULTY")
    assert client.get("/api/alumni", headers=u.headers).status_code == 200
    assert client.patch(f"/api/users/{u.id}", headers=auth, json={"role": "STUDENT"}).status_code == 200
    assert client.get("/api/alumni", headers=u.headers).status_code == 403       # same token, new role


def test_disabling_a_user_ends_their_sessions(client, auth, account):
    u = account("FACULTY")
    assert client.patch(f"/api/users/{u.id}", headers=auth, json={"is_active": False}).status_code == 200
    assert client.get("/api/auth/me", headers=u.headers).status_code == 401
    assert login(client, u.email, u.password).status_code == 401


def test_admin_safety_rails(client, auth):
    me = client.get("/api/auth/me", headers=auth).json()
    assert client.patch(f"/api/users/{me['id']}", headers=auth, json={"is_active": False}).status_code == 409
    assert client.patch(f"/api/users/{me['id']}", headers=auth, json={"role": "FACULTY"}).status_code == 409


def test_last_active_admin_cannot_be_removed(client, auth, account):
    other = account("ADMIN")                      # two admins now
    assert client.patch(f"/api/users/{other.id}", headers=auth, json={"role": "FACULTY"}).status_code == 200
    with db() as c:                               # exercise the guard directly for the sole remaining admin
        sole = c.execute("SELECT id FROM users WHERE role='ADMIN' AND is_active=1").fetchall()
        if len(sole) == 1:
            with pytest.raises(accounts.AccountError):
                accounts.update_user(c, type("A", (), {"user_id": -1}), sole[0]["id"], role="FACULTY")


def test_user_creation_rules(client, auth, import_people):
    aid = list(import_people([("Link Probe", 41000020)]).values())[0]
    base = {"email": "rules@example.com", "password": PW}
    assert client.post("/api/users", headers=auth, json={**base, "role": "ALUMNI"}).status_code == 422                       # needs alumni_id
    assert client.post("/api/users", headers=auth, json={**base, "role": "FACULTY", "alumni_id": aid}).status_code == 422    # only alumni link
    assert client.post("/api/users", headers=auth, json={**base, "role": "BOSS"}).status_code == 422
    assert client.post("/api/users", headers=auth, json={**base, "role": "ALUMNI", "alumni_id": 99999999}).status_code == 404
    assert client.post("/api/users", headers=auth, json={**base, "password": "short1", "role": "STUDENT"}).status_code == 422
    assert client.post("/api/users", headers=auth, json={**base, "password": "onlyletterslong", "role": "STUDENT"}).status_code == 422
    ok = client.post("/api/users", headers=auth, json={**base, "role": "ALUMNI", "alumni_id": aid})
    assert ok.status_code == 200
    assert client.post("/api/users", headers=auth, json={**base, "email": "rules2@example.com", "role": "ALUMNI", "alumni_id": aid}).status_code == 409
    assert client.post("/api/users", headers=auth, json={**base, "role": "STUDENT"}).status_code == 409                       # duplicate email


def test_change_password_keeps_this_device_and_ends_others(client, account):
    u = account("FACULTY")
    second = login(client, u.email, u.password).json()["token"]
    h2 = {"Authorization": "Bearer " + second}
    r = client.post("/api/auth/change-password", headers=u.headers, json={"current_password": "bad", "new_password": "An0ther-Pass-2"})
    assert r.status_code == 403
    r = client.post("/api/auth/change-password", headers=u.headers, json={"current_password": u.password, "new_password": "An0ther-Pass-2"})
    assert r.status_code == 200 and r.json()["other_sessions_ended"] >= 1
    assert client.get("/api/auth/me", headers=u.headers).status_code == 200
    assert client.get("/api/auth/me", headers=h2).status_code == 401
    assert login(client, u.email, "An0ther-Pass-2").status_code == 200


def test_sessions_can_be_listed_and_ended(client, account):
    u = account("FACULTY")
    other = login(client, u.email, u.password).json()["token"]
    items = client.get("/api/auth/sessions", headers=u.headers).json()["items"]
    assert len(items) >= 2 and sum(i["current"] for i in items) == 1
    victim = next(i for i in items if not i["current"])
    assert client.delete(f"/api/auth/sessions/{victim['id']}", headers=u.headers).status_code == 200
    assert client.delete(f"/api/auth/sessions/{victim['id']}", headers=u.headers).status_code == 404
    del other


def test_password_reset_flow(client, account):
    u = account("FACULTY")
    # unknown and known emails get the same answer (no account discovery)
    a = client.post("/api/auth/password-reset/request", json={"email": "ghost@example.com"})
    b = client.post("/api/auth/password-reset/request", json={"email": u.email})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    with db() as c:
        _, raw = accounts.create_password_reset(c, u.email)
    assert client.post("/api/auth/password-reset/confirm", json={"token": raw, "new_password": "weak"}).status_code == 422   # token survives a bad password
    assert client.post("/api/auth/password-reset/confirm", json={"token": raw, "new_password": "Br4nd-New-Pass"}).status_code == 200
    assert client.post("/api/auth/password-reset/confirm", json={"token": raw, "new_password": "Br4nd-New-Pass2"}).status_code == 400  # single use
    assert client.get("/api/auth/me", headers=u.headers).status_code == 401           # old sessions ended
    assert login(client, u.email, "Br4nd-New-Pass").status_code == 200


def test_reset_tokens_expire_and_are_stored_hashed(client, account):
    u = account("FACULTY")
    with db() as c:
        _, raw = accounts.create_password_reset(c, u.email)
        assert c.execute("SELECT COUNT(*) n FROM password_resets WHERE token_hash=?", (raw,)).fetchone()["n"] == 0
        c.execute("UPDATE password_resets SET expires_at='2000-01-01 00:00:00' WHERE user_id=?", (u.id,))
    assert client.post("/api/auth/password-reset/confirm", json={"token": raw, "new_password": "Br4nd-New-Pass"}).status_code == 400


def test_new_reset_request_invalidates_the_previous_link(client, account):
    u = account("FACULTY")
    with db() as c:
        _, first = accounts.create_password_reset(c, u.email)
        _, second = accounts.create_password_reset(c, u.email)
    assert client.post("/api/auth/password-reset/confirm", json={"token": first, "new_password": "Br4nd-New-Pass"}).status_code == 400
    assert client.post("/api/auth/password-reset/confirm", json={"token": second, "new_password": "Br4nd-New-Pass"}).status_code == 200


def test_roles_endpoint_lists_the_matrix(client, auth):
    r = client.get("/api/roles", headers=auth).json()
    assert {x["name"] for x in r["roles"]} == {"ADMIN", "FACULTY", "ALUMNI", "STUDENT"}
    with db() as c:    # the tables mirror the code
        n = c.execute("SELECT COUNT(*) n FROM role_permissions WHERE role='FACULTY'").fetchone()["n"]
    assert n == len(next(x for x in r["roles"] if x["name"] == "FACULTY")["permissions"])
