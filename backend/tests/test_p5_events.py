"""Phase 5: events, registration, and the admin's participant list."""
import itertools
import uuid
from datetime import timedelta

import pytest

from app import events
from app.db import db

_PRN = itertools.count(50000001)


def day(offset):
    return (events.now_local().date() + timedelta(days=offset)).isoformat()


def body(**kw):
    b = {"name": "Annual Alumni Meet " + uuid.uuid4().hex[:6], "description": "An evening of talks and networking on campus.",
         "event_date": day(5), "event_time": "18:30", "venue": "Main Auditorium", "registration_link": ""}
    b.update(kw)
    return b


def make(client, auth, **kw):
    r = client.post("/api/events", headers=auth, json=body(**kw))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def make_started(client, auth, **kw):
    """An event that has already started: created for the future, then moved into the past directly in the database."""
    eid = make(client, auth, **kw)
    with db() as c:
        c.execute("UPDATE events SET event_date=?, event_time='09:00' WHERE id=?", (day(-2), eid))
    return eid


def board(client, who, **params):
    r = client.get("/api/events", headers=who, params={"page_size": 50, **params})
    assert r.status_code == 200, r.text
    return r.json()


def ids(data):
    return [e["id"] for e in data["items"]]


def get(client, who, eid, **params):
    return next(e for e in board(client, who, when="all", **params)["items"] if e["id"] == eid)


# ---------------------------------------------------------------- admin manages, everyone reads
def test_admin_creates_edits_and_deletes(client, auth):
    eid = make(client, auth, name="Career Fair", registration_link="https://forms.example.com/fair")
    e = get(client, auth, eid)
    assert (e["name"], e["event_time"], e["venue"], e["registration_link"]) == ("Career Fair", "18:30", "Main Auditorium", "https://forms.example.com/fair")
    assert e["is_past"] is False and e["can_manage"] is True and e["registration_count"] == 0
    assert client.put(f"/api/events/{eid}", headers=auth, json=body(name="Career Fair 2", event_time="10:00", venue="Seminar Hall")).status_code == 200
    e = get(client, auth, eid)
    assert (e["name"], e["event_time"], e["venue"], e["registration_link"]) == ("Career Fair 2", "10:00", "Seminar Hall", None)     # link cleared
    assert client.delete(f"/api/events/{eid}", headers=auth).json()["deleted"] is True
    assert eid not in ids(board(client, auth, when="all"))
    assert client.delete(f"/api/events/{eid}", headers=auth).status_code == 404
    assert client.put("/api/events/999999", headers=auth, json=body()).status_code == 404


def test_only_admins_manage_everyone_signed_in_reads(client, auth, account):
    eid = make(client, auth)
    for role in ("STUDENT", "FACULTY"):
        who = account(role).headers
        assert client.post("/api/events", headers=who, json=body()).status_code == 403
        assert client.put(f"/api/events/{eid}", headers=who, json=body()).status_code == 403
        assert client.delete(f"/api/events/{eid}", headers=who).status_code == 403
        assert client.get(f"/api/events/{eid}/registrations", headers=who).status_code == 403
        item = get(client, who, eid)
        assert item["can_manage"] is False and item["registration_count"] is None and item["name"]
    assert client.get("/api/events").status_code == 401
    assert client.post("/api/events", json=body()).status_code == 401
    assert client.post(f"/api/events/{eid}/register").status_code == 401


def test_validation(client, auth):
    bad = [{"name": "ab"}, {"name": "x" * 151}, {"description": "short"}, {"description": "d" * 3001}, {"venue": "A"},
           {"event_date": "tomorrow"}, {"event_date": day(-1)}, {"event_date": day(800)}, {"event_date": "2026-02-30"},
           {"event_time": "6pm"}, {"event_time": "25:00"}, {"event_time": "18:60"}, {"event_time": ""},
           {"registration_link": "http://plain.example.com"}, {"registration_link": "javascript:alert(1)"}, {"registration_link": "https://localhost/x"}]
    for change in bad:
        assert client.post("/api/events", headers=auth, json=body(**change)).status_code == 422, change
    ok = client.post("/api/events", headers=auth, json=body(name="  Spaced   name ", event_time="00:00", event_date=day(0), registration_link="forms.example.com/x"))
    assert ok.status_code == 200
    e = get(client, auth, ok.json()["id"])
    assert e["name"] == "Spaced name" and e["registration_link"].startswith("https://forms.example.com")


# ---------------------------------------------------------------- what the board shows
def test_upcoming_past_search_and_order(client, auth, account):
    later = make(client, auth, name="Zulu Talk", event_date=day(20), event_time="11:00")
    sooner = make(client, auth, name="Zulu Workshop", event_date=day(4), event_time="09:00")
    gone = make_started(client, auth, name="Zulu Reunion")
    stu = account("STUDENT").headers
    default = board(client, stu)
    assert gone not in ids(default) and {later, sooner} <= set(ids(default))
    order = ids(default)
    assert order.index(sooner) < order.index(later)                                  # soonest first
    assert ids(board(client, stu, when="past", search="zulu")) == [gone]
    allv = ids(board(client, stu, when="all", search="zulu"))
    assert allv == [sooner, later, gone]                                             # upcoming (soonest first), then past
    assert get(client, stu, gone)["is_past"] is True and get(client, stu, sooner)["is_past"] is False
    assert ids(board(client, stu, search="main auditorium")) and board(client, stu, search="100%")["total"] == 0
    assert client.get("/api/events", headers=stu, params={"when": "never"}).status_code == 422
    p = board(client, stu, when="all", search="zulu", page_size=2, page=2)
    assert p["total"] == 3 and ids(p) == [gone]


# ---------------------------------------------------------------- registering
def test_register_and_cancel(client, auth, account):
    eid = make(client, auth)
    stu, fac = account("STUDENT"), account("FACULTY")
    assert get(client, stu.headers, eid)["registered"] is False and get(client, stu.headers, eid)["can_register"] is True
    assert client.post(f"/api/events/{eid}/register", headers=stu.headers).json() == {"id": eid, "registered": True}
    mine = get(client, stu.headers, eid)
    assert mine["registered"] is True and mine["can_register"] is False
    assert get(client, fac.headers, eid)["registered"] is False                      # registration is per person
    dup = client.post(f"/api/events/{eid}/register", headers=stu.headers)
    assert dup.status_code == 409 and "already registered" in dup.json()["detail"]
    assert client.post(f"/api/events/{eid}/register", headers=fac.headers).status_code == 200
    assert client.delete(f"/api/events/{eid}/register", headers=stu.headers).json()["registered"] is False
    assert get(client, stu.headers, eid)["registered"] is False and get(client, fac.headers, eid)["registered"] is True
    assert client.delete(f"/api/events/{eid}/register", headers=stu.headers).status_code == 404       # not registered any more
    assert client.post(f"/api/events/{eid}/register", headers=stu.headers).status_code == 200          # and can register again
    assert client.post("/api/events/999999/register", headers=stu.headers).status_code == 404


def test_alumni_can_register_too(client, auth, account, import_people):
    aid = list(import_people([(f"Event Alum{next(_PRN)}", next(_PRN))], year=2095).values())[0]
    alum = account("ALUMNI", aid)
    eid = make(client, auth)
    assert client.post(f"/api/events/{eid}/register", headers=alum.headers).status_code == 200


def test_registration_closes_when_the_event_starts(client, auth, account):
    eid = make(client, auth)
    stu = account("STUDENT").headers
    client.post(f"/api/events/{eid}/register", headers=stu)
    with db() as c:
        c.execute("UPDATE events SET event_date=?, event_time='09:00' WHERE id=?", (day(-1), eid))
    late = account("STUDENT").headers
    r = client.post(f"/api/events/{eid}/register", headers=late)
    assert r.status_code == 409 and "already started" in r.json()["detail"]
    assert client.delete(f"/api/events/{eid}/register", headers=stu).status_code == 409           # the record of who signed up stays
    e = get(client, stu, eid)
    assert e["is_past"] is True and e["can_register"] is False and e["registered"] is True


def test_database_allows_one_registration_per_person(client, auth, account):
    import sqlite3
    eid = make(client, auth)
    stu = account("STUDENT")
    client.post(f"/api/events/{eid}/register", headers=stu.headers)
    with db() as c:
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO event_registrations(event_id,user_id,registered_at) VALUES(?,?,?)", (eid, stu.id, "2030-01-01 00:00:00"))


# ---------------------------------------------------------------- the admin's view
def test_admin_sees_counts_and_participants_nobody_else_does(client, auth, account, import_people):
    aid = list(import_people([("Event Alumna Priya", next(_PRN))], year=2096).values())[0]
    alum, stu = account("ALUMNI", aid), account("STUDENT")
    eid = make(client, auth, name="Counted Event")
    client.post(f"/api/events/{eid}/register", headers=alum.headers)
    client.post(f"/api/events/{eid}/register", headers=stu.headers)
    assert get(client, auth, eid)["registration_count"] == 2
    assert get(client, stu.headers, eid)["registration_count"] is None
    r = client.get(f"/api/events/{eid}/registrations", headers=auth).json()
    assert r["count"] == 2 and r["event"]["name"] == "Counted Event"
    by_email = {p["email"]: p for p in r["items"]}
    assert by_email[alum.email]["name"] == "Event Alumna Priya" and by_email[alum.email]["graduation_year"] == 2096 and by_email[alum.email]["role"] == "ALUMNI"
    assert by_email[stu.email]["role"] == "STUDENT" and by_email[stu.email]["graduation_year"] is None and by_email[stu.email]["name"]
    assert all(p["registered_at"] for p in r["items"])
    assert client.get("/api/events/999999/registrations", headers=auth).status_code == 404


# ---------------------------------------------------------------- editing and deleting
def test_editing_keeps_registrations_and_respects_the_date_rule(client, auth, account):
    eid = make_started(client, auth, name="Old event")
    past = day(-2)
    assert client.put(f"/api/events/{eid}", headers=auth, json=body(name="Typo fixed", event_date=past)).status_code == 200      # date unchanged
    assert client.put(f"/api/events/{eid}", headers=auth, json=body(event_date=day(-1))).status_code == 422                        # new past date
    live = make(client, auth)
    stu = account("STUDENT").headers
    client.post(f"/api/events/{live}/register", headers=stu)
    assert client.put(f"/api/events/{live}", headers=auth, json=body(name="Renamed", event_date=day(9))).status_code == 200
    assert get(client, stu, live)["registered"] is True and get(client, auth, live)["registration_count"] == 1


def test_deleting_an_event_removes_its_registrations(client, auth, account):
    eid = make(client, auth, name="Doomed Event")
    for _ in range(2):
        client.post(f"/api/events/{eid}/register", headers=account("STUDENT").headers)
    assert client.delete(f"/api/events/{eid}", headers=auth).status_code == 200
    with db() as c:
        assert c.execute("SELECT COUNT(*) n FROM event_registrations WHERE event_id=?", (eid,)).fetchone()["n"] == 0
    log = [r for r in client.get("/api/audit-logs", headers=auth, params={"entity_type": "event", "page_size": 100}).json()["items"]
           if str(r["entity_id"]) == str(eid) and r["action"] == "event.delete"][0]
    assert log["detail"]["registrations_removed"] == 2


def test_actions_are_audited(client, auth, account):
    eid = make(client, auth)
    stu = account("STUDENT").headers
    client.put(f"/api/events/{eid}", headers=auth, json=body(name="Audited v2"))
    client.post(f"/api/events/{eid}/register", headers=stu)
    client.delete(f"/api/events/{eid}/register", headers=stu)
    rows = client.get("/api/audit-logs", headers=auth, params={"entity_type": "event", "page_size": 100}).json()["items"]
    assert {"event.create", "event.update", "event.register", "event.cancel"} <= {r["action"] for r in rows if str(r["entity_id"]) == str(eid)}
