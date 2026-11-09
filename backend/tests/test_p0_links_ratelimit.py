"""Phase 0: expiring/revocable personal links, and rate limiting."""
import time

import pytest

from app import config, notifier, ratelimit, services
from app.db import db

FORM = {"career_status": "EMPLOYMENT", "details": {"company": "X", "designation": "Y", "industry": "Z"}}


def _token(client, auth, aid):
    return client.get(f"/api/alumni/{aid}", headers=auth).json()["link"].split("token=")[1]


def _one(import_people, prn):
    aid = list(import_people([("Link Person", prn)]).values())[0]
    return aid


def test_new_links_have_an_expiry(client, auth, import_people):
    aid = _one(import_people, 42000001)
    a = client.get(f"/api/alumni/{aid}", headers=auth).json()
    assert a["link_status"] == "active" and a["token_expires_at"]
    assert client.get(f"/api/public/form?token={_token(client, auth, aid)}").status_code == 200


def test_expired_link_is_gone_for_form_and_submit(client, auth, import_people):
    aid = _one(import_people, 42000002)
    tok = _token(client, auth, aid)
    with db() as c:
        c.execute("UPDATE alumni SET token_expires_at='2000-01-01 00:00:00' WHERE id=?", (aid,))
    r = client.get(f"/api/public/form?token={tok}")
    assert r.status_code == 410 and "expired" in r.json()["detail"]
    assert client.post("/api/public/submit", json={"token": tok, **FORM}).status_code == 410
    assert client.get(f"/api/alumni/{aid}", headers=auth).json()["link_status"] == "expired"


def test_unknown_and_malformed_tokens_are_404_not_410(client):
    assert client.get("/api/public/form?token=" + "a" * 30).status_code == 404
    assert client.get("/api/public/form?token=short").status_code == 404


def test_regenerate_replaces_the_link_immediately(client, auth, import_people):
    aid = _one(import_people, 42000003)
    old = _token(client, auth, aid)
    r = client.post(f"/api/alumni/{aid}/link/regenerate", headers=auth).json()
    new = r["link"].split("token=")[1]
    assert new != old and r["link_status"] == "active"
    assert client.get(f"/api/public/form?token={old}").status_code == 404
    assert client.get(f"/api/public/form?token={new}").status_code == 200


def test_revoke_disables_link_and_excludes_from_reminders(client, auth, import_people):
    ids = import_people([("Rev One", 42000004), ("Rev Two", 42000005)], year=2042)
    a, b = ids[42000004], ids[42000005]
    cid = client.post("/api/campaigns", headers=auth, json={"name": "rev", "recipients": {"alumni_ids": [a, b]}}).json()["id"]
    reach = lambda: next(c for c in client.get("/api/campaigns", headers=auth).json()["items"] if c["id"] == cid)["reachable"]
    assert reach() == 2
    tok = _token(client, auth, a)
    assert client.post(f"/api/alumni/{a}/link/revoke", headers=auth).json()["link_status"] == "revoked"
    r = client.get(f"/api/public/form?token={tok}")
    assert r.status_code == 410 and "disabled" in r.json()["detail"]
    assert reach() == 1                                           # no reminder carries a dead link
    client.post(f"/api/alumni/{a}/link/regenerate", headers=auth)
    assert reach() == 2                                           # a fresh link puts them back


def test_link_actions_need_permission_and_a_known_action(client, auth, account, import_people):
    aid = _one(import_people, 42000006)
    assert client.post(f"/api/alumni/{aid}/link/regenerate", headers=account("ALUMNI", aid).headers).status_code == 403
    assert client.post(f"/api/alumni/{aid}/link/explode", headers=auth).status_code == 404
    assert client.post("/api/alumni/99999999/link/revoke", headers=auth).status_code == 404


def test_sending_a_reminder_renews_a_link(client, auth, import_people):
    aid = _one(import_people, 42000007)
    with db() as c:
        c.execute("UPDATE alumni SET token_expires_at=? WHERE id=?", (services.iso(services.now() + services.timedelta(days=1)), aid))
        services.extend_token(c, aid)
        exp = c.execute("SELECT token_expires_at e FROM alumni WHERE id=?", (aid,)).fetchone()["e"]
    assert exp > services.iso(services.now() + services.timedelta(days=config.TOKEN_TTL_DAYS - 1))


def test_renewal_never_revives_a_revoked_link(client, auth, import_people):
    aid = _one(import_people, 42000008)
    client.post(f"/api/alumni/{aid}/link/revoke", headers=auth)
    with db() as c:
        services.extend_token(c, aid)
        assert services.token_state(c.execute("SELECT * FROM alumni WHERE id=?", (aid,)).fetchone()) == "revoked"


def test_missing_expiry_fails_closed():
    assert services.token_state({"token_revoked_at": None, "token_expires_at": None}) == "expired"


def test_telegram_start_ignores_expired_links(client, auth, import_people, monkeypatch):
    aid = _one(import_people, 42000009)
    tok = _token(client, auth, aid)
    with db() as c:
        c.execute("UPDATE alumni SET token_expires_at='2000-01-01 00:00:00' WHERE id=?", (aid,))
    sent = []
    monkeypatch.setattr(notifier, "telegram_configured", lambda: True)
    monkeypatch.setattr(notifier, "fetch_telegram_updates", lambda off: [{"update_id": 10 ** 9, "message": {"chat": {"type": "private", "id": 777}, "text": f"/start {tok}"}}])
    monkeypatch.setattr(notifier, "send_telegram", lambda chat, text: sent.append(text))
    try:
        assert services.poll_telegram() == 0
        with db() as c:
            assert c.execute("SELECT telegram_chat_id t FROM alumni WHERE id=?", (aid,)).fetchone()["t"] is None
    finally:                                   # poll_telegram stores an offset in shared state; leave none behind for other tests
        with db() as c:
            c.execute("DELETE FROM settings WHERE key='telegram_offset'")


# ---------------------------------------------------------------- rate limiting
def test_public_form_is_rate_limited_with_retry_after(client, monkeypatch):
    monkeypatch.setitem(ratelimit.LIMITS, "public_read", (3, 60))
    for _ in range(3):
        assert client.get("/api/public/form?token=" + "a" * 30).status_code == 404
    r = client.get("/api/public/form?token=" + "a" * 30)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_public_submit_is_rate_limited(client, monkeypatch):
    monkeypatch.setitem(ratelimit.LIMITS, "public_write", (2, 60))
    for _ in range(2):
        assert client.post("/api/public/submit", json={"token": "a" * 30, **FORM}).status_code == 404
    assert client.post("/api/public/submit", json={"token": "a" * 30, **FORM}).status_code == 429


def test_login_is_rate_limited_per_account(client, monkeypatch):
    monkeypatch.setitem(ratelimit.LIMITS, "login", (3, 600))
    for _ in range(3):
        assert client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"}).status_code == 429
    assert client.post("/api/auth/login", json={"email": "other@example.com", "password": "x"}).status_code == 401   # different account, own budget


def test_password_reset_request_is_rate_limited(client, monkeypatch):
    monkeypatch.setitem(ratelimit.LIMITS, "reset_request", (2, 60))
    for _ in range(2):
        assert client.post("/api/auth/password-reset/request", json={"email": "g@example.com"}).status_code == 200
    assert client.post("/api/auth/password-reset/request", json={"email": "g@example.com"}).status_code == 429


def test_limiter_window_expires_and_can_be_disabled(monkeypatch):
    lim = ratelimit.RateLimiter()
    assert lim.hit("b", "k", 2, 60)[0] and lim.hit("b", "k", 2, 60)[0] and not lim.hit("b", "k", 2, 60)[0]
    quick = ratelimit.RateLimiter()
    assert quick.hit("b", "k", 1, 0.05)[0] and not quick.hit("b", "k", 1, 0.05)[0]
    time.sleep(0.08)
    assert quick.hit("b", "k", 1, 0.05)[0]                    # the window slid past the first hit
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setitem(ratelimit.LIMITS, "public_read", (1, 60))
    for _ in range(5):
        ratelimit.check("public_read", "x")          # never raises while disabled


def test_limiter_memory_is_bounded():
    lim = ratelimit.RateLimiter(max_keys=100)
    for i in range(1000):
        lim.hit("b", f"k{i}", 5, 60)
    assert len(lim._hits) <= 100


class _Req:
    def __init__(self, xff=None, host="9.9.9.9"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": host})()


def test_client_ip_ignores_forwarded_header_unless_proxies_are_configured(monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY_HOPS", 0)
    assert ratelimit.client_ip(_Req("1.2.3.4")) == "9.9.9.9"
    monkeypatch.setattr(config, "TRUST_PROXY_HOPS", 2)       # ngrok -> vite -> api
    assert ratelimit.client_ip(_Req("5.6.7.8, 127.0.0.1")) == "5.6.7.8"
    assert ratelimit.client_ip(_Req("6.6.6.6, 5.6.7.8, 127.0.0.1")) == "5.6.7.8"      # a forged leading entry changes nothing
    assert ratelimit.client_ip(_Req()) == "9.9.9.9"
