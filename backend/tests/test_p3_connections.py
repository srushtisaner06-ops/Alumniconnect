"""Phase 3: connection requests between alumni, and the privacy rules around them."""
import itertools
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import connections
from app.db import db

_PRN = itertools.count(47000001)
_YEAR = itertools.count(2071)
CONTACT_KEYS = {"email", "phone", "whatsapp", "prn", "token", "salary", "package_lpa"}


class Person:
    def __init__(self, aid, acct):
        self.aid, self.h = aid, acct.headers


@pytest.fixture
def people(client, auth, account, import_people):
    """Make(n) -> n alumni, each with a signed-in account and a PUBLIC profile (so they can see each other)."""
    def make(n=2, level="PUBLIC", names=None):
        year = next(_YEAR)
        names = names or [f"Conn Person{i}" for i in range(n)]
        recs = [(nm, next(_PRN)) for nm in names]
        ids = import_people(recs, year=year)
        out = []
        for nm, prn in recs:
            p = Person(ids[prn], account("ALUMNI", ids[prn]))
            if level:
                assert client.put("/api/profile/me/visibility", headers=p.h, json={"level": level}).status_code == 200
            out.append(p)
        return out
    return make


def ask(client, frm, to, message=None):
    return client.post("/api/connections", headers=frm.h, json={"recipient_id": to.aid, "message": message})


def box(client, p):
    r = client.get("/api/connections", headers=p.h)
    assert r.status_code == 200, r.text
    return r.json()


def keys_in(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys_in(v)


# ---------------------------------------------------------------- the happy path
def test_request_accept_flow_shows_in_every_list(client, people):
    a, b = people(2)
    r = ask(client, a, b, "  Hi,   we were in   the same batch  ")
    assert r.status_code == 200 and r.json()["status"] == "PENDING"
    sent, got = box(client, a), box(client, b)
    assert [x["person"]["id"] for x in sent["sent"]] == [b.aid] and sent["received"] == [] and sent["connections"] == []
    assert [x["person"]["id"] for x in got["received"]] == [a.aid] and got["sent"] == []
    assert got["received"][0]["message"] == "Hi, we were in the same batch"          # whitespace tidied
    cid = got["received"][0]["id"]

    assert client.post(f"/api/connections/{cid}/accept", headers=b.h).json()["status"] == "ACCEPTED"
    for p, other in ((a, b), (b, a)):
        v = box(client, p)
        assert [x["person"]["id"] for x in v["connections"]] == [other.aid]
        assert v["received"] == [] and v["sent"] == [] and v["counts"]["connections"] == 1
    # an accepted connection shows the shared profile (name, batch, headline...) but nothing private
    person = box(client, a)["connections"][0]["person"]
    assert person["name"] and person["graduation_year"] and person["profile_visible"] is True


def test_reject_is_visible_to_sender_and_blocks_immediate_resend(client, people):
    a, b = people(2)
    ask(client, a, b)
    cid = box(client, b)["received"][0]["id"]
    assert client.post(f"/api/connections/{cid}/reject", headers=b.h).json()["status"] == "REJECTED"
    assert box(client, b)["received"] == []                                            # gone from the recipient's inbox
    sent = box(client, a)["sent"]
    assert [x["status"] for x in sent] == ["REJECTED"]                                 # the sender can see the outcome
    again = ask(client, a, b)
    assert again.status_code == 409 and "declined" in again.json()["detail"]
    assert ask(client, b, a).status_code == 200                                        # the person who declined may still reach out


def test_resend_allowed_after_the_cool_down(client, people):
    a, b = people(2)
    ask(client, a, b)
    cid = box(client, b)["received"][0]["id"]
    client.post(f"/api/connections/{cid}/reject", headers=b.h)
    old = (datetime.now(timezone.utc) - timedelta(days=connections.RETRY_AFTER_REJECTION_DAYS + 1)).strftime("%Y-%m-%d %H:%M:%S")
    with db() as c:
        c.execute("UPDATE connections SET responded_at=? WHERE id=?", (old, cid))
    assert ask(client, a, b).status_code == 200


# ---------------------------------------------------------------- one live relationship per pair
def test_duplicate_reverse_self_and_already_connected_are_refused(client, people):
    a, b = people(2)
    assert ask(client, a, a).status_code == 422
    assert ask(client, a, b).status_code == 200
    dup = ask(client, a, b)
    assert dup.status_code == 409 and "already sent" in dup.json()["detail"]
    rev = ask(client, b, a)
    assert rev.status_code == 409 and "already sent you" in rev.json()["detail"]
    cid = box(client, b)["received"][0]["id"]
    client.post(f"/api/connections/{cid}/accept", headers=b.h)
    for x, y in ((a, b), (b, a)):
        r = ask(client, x, y)
        assert r.status_code == 409 and "already connected" in r.json()["detail"]


def test_database_itself_refuses_two_live_rows_for_a_pair(people):
    a, b = people(2)
    now = "2030-01-01 00:00:00"
    with db() as c:
        c.execute("INSERT INTO connections(requester_id,recipient_id,pair_key,status,created_at) VALUES(?,?,?,?,?)",
                  (a.aid, b.aid, connections.pair_key(a.aid, b.aid), "PENDING", now))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO connections(requester_id,recipient_id,pair_key,status,created_at) VALUES(?,?,?,?,?)",
                      (b.aid, a.aid, connections.pair_key(b.aid, a.aid), "PENDING", now))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO connections(requester_id,recipient_id,pair_key,status,created_at) VALUES(?,?,?,?,?)",
                      (a.aid, a.aid, "x", "PENDING", now))


def test_pending_cap(client, people, monkeypatch):
    monkeypatch.setattr(connections, "MAX_PENDING_SENT", 2)
    a, b, c3, d = people(4)
    assert ask(client, a, b).status_code == 200 and ask(client, a, c3).status_code == 200
    r = ask(client, a, d)
    assert r.status_code == 429 and "waiting for a reply" in r.json()["detail"]


# ---------------------------------------------------------------- withdraw / remove
def test_withdraw_and_remove(client, people):
    a, b = people(2)
    ask(client, a, b)
    cid = box(client, a)["sent"][0]["id"]
    assert client.delete(f"/api/connections/{cid}", headers=b.h).status_code == 409        # recipient must Reject, not withdraw
    assert client.delete(f"/api/connections/{cid}", headers=a.h).json()["status"] == "CANCELLED"
    assert box(client, a)["sent"] == [] and box(client, b)["received"] == []
    assert client.post(f"/api/connections/{cid}/accept", headers=b.h).status_code == 409   # a withdrawn request cannot be accepted
    assert client.delete(f"/api/connections/{cid}", headers=a.h).status_code == 409        # nothing left to remove

    assert ask(client, a, b).status_code == 200                                            # asking again after a withdrawal is fine
    cid = box(client, b)["received"][0]["id"]
    client.post(f"/api/connections/{cid}/accept", headers=b.h)
    assert client.delete(f"/api/connections/{cid}", headers=b.h).status_code == 200        # either person can end it
    assert box(client, a)["connections"] == [] and box(client, b)["connections"] == []
    assert ask(client, b, a).status_code == 200                                            # and reconnect later


def test_only_the_recipient_can_answer_and_strangers_see_nothing(client, people):
    a, b, stranger = people(3)
    ask(client, a, b)
    cid = box(client, b)["received"][0]["id"]
    assert client.post(f"/api/connections/{cid}/accept", headers=a.h).status_code == 403      # the sender cannot accept their own request
    for verb in ("accept", "reject"):
        assert client.post(f"/api/connections/{cid}/{verb}", headers=stranger.h).status_code == 404
    assert client.delete(f"/api/connections/{cid}", headers=stranger.h).status_code == 404
    assert client.post("/api/connections/999999/accept", headers=b.h).status_code == 404
    assert box(client, stranger) == {"received": [], "sent": [], "connections": [], "counts": {"received": 0, "sent": 0, "connections": 0}, "me": stranger.aid}
    assert client.post(f"/api/connections/{cid}/accept", headers=b.h).status_code == 200
    assert client.post(f"/api/connections/{cid}/reject", headers=b.h).status_code == 409      # answered once only


# ---------------------------------------------------------------- privacy
def test_cannot_connect_to_a_profile_you_cannot_see(client, people):
    a, hidden = people(2)
    client.put("/api/profile/me/visibility", headers=hidden.h, json={"level": "PRIVATE"})
    real = ask(client, a, hidden)
    ghost = client.post("/api/connections", headers=a.h, json={"recipient_id": 987654})
    assert real.status_code == ghost.status_code == 404 and real.json() == ghost.json()      # a private profile looks like a missing one
    assert box(client, hidden)["received"] == []


def test_private_requester_shows_only_name_and_batch(client, auth, people):
    a, b = people(2)
    client.put(f"/api/alumni/{a.aid}/profile", headers=auth, json={"headline": "Secret headline", "city": "Pune"})
    client.put("/api/profile/me/visibility", headers=a.h, json={"level": "PRIVATE"})        # a hides their profile, then asks b
    assert ask(client, a, b).status_code == 200
    person = box(client, b)["received"][0]["person"]
    assert person["profile_visible"] is False and set(person) == {"id", "name", "graduation_year", "profile_visible"}
    assert "Secret headline" not in json.dumps(box(client, b))


def test_hiding_your_profile_later_hides_it_from_existing_connections(client, auth, people):
    a, b = people(2)
    client.put(f"/api/alumni/{a.aid}/profile", headers=auth, json={"headline": "Findable headline"})
    ask(client, a, b)
    client.post(f"/api/connections/{box(client, b)['received'][0]['id']}/accept", headers=b.h)
    assert "Findable headline" in json.dumps(box(client, b)["connections"])
    client.put("/api/profile/me/visibility", headers=a.h, json={"level": "PRIVATE"})
    after = box(client, b)["connections"][0]["person"]
    assert after["profile_visible"] is False and "Findable headline" not in json.dumps(box(client, b))


def test_contact_details_never_appear_even_after_accepting(client, auth, people):
    a, b = people(2)
    for p in (a, b):
        client.put(f"/api/alumni/{p.aid}/profile", headers=auth, json={"whatsapp": "+919876543210", "headline": "Engineer"})
    ask(client, a, b, "hello")
    client.post(f"/api/connections/{box(client, b)['received'][0]['id']}/accept", headers=b.h)
    for p in (a, b):
        data = box(client, p)
        text = json.dumps(data)
        assert not (CONTACT_KEYS & set(keys_in(data)))
        assert "9876543210" not in text and "@" not in text
        assert data["connections"][0]["person"]["profile"]["headline"] == "Engineer"


# ---------------------------------------------------------------- who may use it
def test_permissions(client, auth, account, people):
    a, b = people(2)
    student = account("STUDENT")
    assert client.get("/api/connections", headers=student.headers).status_code == 403
    assert client.post("/api/connections", headers=student.headers, json={"recipient_id": b.aid}).status_code == 403
    assert client.get("/api/connections").status_code == 401
    assert client.post("/api/connections", json={"recipient_id": b.aid}).status_code == 401
    assert client.get("/api/connections", headers=auth).status_code == 404                  # an admin has no alumni record to connect as
    r = ask(client, a, b, "x" * (connections.MESSAGE_MAX + 1))
    assert r.status_code == 422
    assert ask(client, a, b, "y" * connections.MESSAGE_MAX).status_code == 200


def test_actions_are_audited(client, auth, people):
    a, b = people(2)
    ask(client, a, b)
    cid = box(client, b)["received"][0]["id"]
    client.post(f"/api/connections/{cid}/accept", headers=b.h)
    client.delete(f"/api/connections/{cid}", headers=a.h)
    actions = [r["action"] for r in client.get("/api/audit-logs", headers=auth, params={"entity_type": "connection", "page_size": 50}).json()["items"]
               if str(r["entity_id"]) == str(cid)]
    assert {"connection.request", "connection.accept", "connection.remove"} <= set(actions)


def test_connections_disappear_when_an_alumnus_record_is_deleted(client, auth, people):
    a, b = people(2)
    ask(client, a, b)
    assert client.delete(f"/api/alumni/{a.aid}", headers=auth).status_code == 200
    with db() as c:
        assert c.execute("SELECT COUNT(*) n FROM connections WHERE requester_id=? OR recipient_id=?", (a.aid, a.aid)).fetchone()["n"] == 0
