"""Phase 4: the opportunities board."""
import itertools
from datetime import date, timedelta

import pytest

from app import opportunities
from app.db import db

_PRN = itertools.count(48000001)
_YEAR = itertools.count(2081)


def when(days):
    return (date.fromisoformat(opportunities.today()) + timedelta(days=days)).isoformat()


def post_body(**kw):
    body = {"category": "JOB", "title": "Backend Engineer", "company": "Acme Corp", "description": "Build APIs for our payments team.",
            "apply_contact": "https://acme.example/careers/42", "closing_date": when(10)}
    body.update(kw)
    return body


@pytest.fixture
def alumni(account, import_people):
    """Make(n) -> n alumni with accounts (each has .aid and .headers)."""
    def make(n=1):
        year = next(_YEAR)
        recs = [(f"Opp Person{next(_PRN)}", next(_PRN)) for _ in range(n)]
        ids = import_people(recs, year=year)
        out = []
        for nm, prn in recs:
            acct = account("ALUMNI", ids[prn])
            acct.aid, acct.name, acct.year = ids[prn], nm, year
            out.append(acct)
        return out
    return make


def make_post(client, who, **kw):
    r = client.post("/api/opportunities", headers=who, json=post_body(**kw))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def board(client, who, **params):
    r = client.get("/api/opportunities", headers=who, params={"page_size": 50, **params})
    assert r.status_code == 200, r.text
    return r.json()


def ids(data):
    return [i["id"] for i in data["items"]]


# ---------------------------------------------------------------- create and read
def test_alumnus_posts_and_everyone_signed_in_can_read(client, auth, account, alumni):
    (a,) = alumni(1)
    oid = make_post(client, a.headers, category="INTERNSHIP", title="Summer Intern", apply_contact="Hr@Acme.EXAMPLE")
    for who in (a.headers, account("STUDENT").headers, account("FACULTY").headers, auth):
        item = next(i for i in board(client, who)["items"] if i["id"] == oid)
        assert item["category"] == "INTERNSHIP" and item["category_label"] == "Internship" and item["title"] == "Summer Intern"
        assert item["apply_contact"] == "hr@acme.example" and item["apply_kind"] == "email"      # emails are normalised
        assert item["posted_by"] == {"name": a.name, "graduation_year": a.year} and item["is_closed"] is False
    assert client.get("/api/opportunities").status_code == 401


def test_who_may_post(client, auth, account, alumni):
    (a,) = alumni(1)
    assert client.post("/api/opportunities", headers=account("STUDENT").headers, json=post_body()).status_code == 403
    assert client.post("/api/opportunities", headers=account("FACULTY").headers, json=post_body()).status_code == 403
    assert client.post("/api/opportunities", json=post_body()).status_code == 401
    assert client.post("/api/opportunities", headers=a.headers, json=post_body()).status_code == 200
    r = client.post("/api/opportunities", headers=auth, json=post_body(title="Admin posted"))      # admins have no alumni record
    assert r.status_code == 200
    item = next(i for i in board(client, auth)["items"] if i["id"] == r.json()["id"])
    assert item["posted_by"]["name"] and item["posted_by"]["graduation_year"] is None


def test_validation(client, alumni):
    (a,) = alumni(1)
    bad = [
        {"category": "SCHOLARSHIP"}, {"category": ""}, {"title": "ab"}, {"title": "x" * 121}, {"company": "A"},
        {"description": "short"}, {"description": "d" * 2001},
        {"apply_contact": ""}, {"apply_contact": "http://acme.example/jobs"}, {"apply_contact": "javascript:alert(1)"},
        {"apply_contact": "not an email@"}, {"apply_contact": "https://localhost/x"},
        {"closing_date": "soon"}, {"closing_date": when(-1)}, {"closing_date": when(400)},
    ]
    for change in bad:
        r = client.post("/api/opportunities", headers=a.headers, json=post_body(**change))
        assert r.status_code == 422, change
    ok = post_body(closing_date=when(0), apply_contact="acme.example/jobs", title="  Spaced    title  ", category="referral")
    r = client.post("/api/opportunities", headers=a.headers, json=ok)
    assert r.status_code == 200                                                    # today is still open; bare domain gets https://
    item = next(i for i in board(client, a.headers)["items"] if i["id"] == r.json()["id"])
    assert item["apply_contact"].startswith("https://acme.example") and item["title"] == "Spaced title" and item["category"] == "REFERRAL"


def test_open_post_cap(client, alumni, monkeypatch):
    monkeypatch.setattr(opportunities, "MAX_OPEN_PER_USER", 2)
    (a,) = alumni(1)
    make_post(client, a.headers)
    make_post(client, a.headers)
    r = client.post("/api/opportunities", headers=a.headers, json=post_body())
    assert r.status_code == 429


# ---------------------------------------------------------------- closing dates
def test_closed_posts_are_hidden_by_default_and_marked_when_shown(client, alumni):
    (a,) = alumni(1)
    open_id = make_post(client, a.headers, title="Still open", closing_date=when(5))
    today_id = make_post(client, a.headers, title="Closes today", closing_date=when(0))
    old_id = make_post(client, a.headers, title="Already closed")
    with db() as c:
        c.execute("UPDATE opportunities SET closing_date=? WHERE id=?", (when(-3), old_id))
    default = board(client, a.headers)
    assert old_id not in ids(default) and {open_id, today_id} <= set(ids(default))
    assert ids(board(client, a.headers, status="closed")) == [old_id]
    everything = board(client, a.headers, status="all")
    flags = {i["id"]: i["is_closed"] for i in everything["items"]}
    assert flags[old_id] is True and flags[open_id] is False and flags[today_id] is False
    order = ids(everything)
    assert order.index(today_id) < order.index(open_id) < order.index(old_id)        # soonest-closing first, closed last
    assert client.get("/api/opportunities", headers=a.headers, params={"status": "nope"}).status_code == 422


# ---------------------------------------------------------------- filters
def test_category_search_and_mine(client, alumni):
    a, b = alumni(2)
    j = make_post(client, a.headers, title="Zebra Developer", company="Stripes Ltd", category="JOB")
    i = make_post(client, a.headers, title="Zebra Intern", category="INTERNSHIP")
    r = make_post(client, b.headers, title="Giraffe Referral", description="Happy to refer strong candidates.", category="REFERRAL")
    assert set(ids(board(client, a.headers, category="JOB"))) >= {j} and i not in ids(board(client, a.headers, category="JOB"))
    assert ids(board(client, a.headers, category="INTERNSHIP", search="zebra")) == [i]
    assert set(ids(board(client, a.headers, search="stripes"))) == {j}               # company is searched
    assert set(ids(board(client, a.headers, search="refer strong"))) == {r}          # and the description
    assert board(client, a.headers, search="100%")["total"] == 0                     # % is literal
    assert set(ids(board(client, a.headers, mine="true"))) == {j, i}
    assert set(ids(board(client, b.headers, mine="true"))) == {r}
    assert client.get("/api/opportunities", headers=a.headers, params={"category": "NOPE"}).status_code == 422
    p1 = board(client, a.headers, search="Zebra", page_size=1, page=1)
    assert p1["total"] == 2 and len(p1["items"]) == 1


# ---------------------------------------------------------------- edit and delete
def test_owner_can_edit_and_delete_others_cannot(client, auth, account, alumni):
    a, b = alumni(2)
    oid = make_post(client, a.headers, title="Original title")
    assert client.put(f"/api/opportunities/{oid}", headers=a.headers, json=post_body(title="Edited title", category="REFERRAL")).status_code == 200
    item = next(x for x in board(client, a.headers)["items"] if x["id"] == oid)
    assert item["title"] == "Edited title" and item["category"] == "REFERRAL" and item["can_edit"] and item["mine"]
    other = next(x for x in board(client, b.headers)["items"] if x["id"] == oid)
    assert other["can_edit"] is False and other["mine"] is False
    for who in (b.headers, account("STUDENT").headers, account("FACULTY").headers):
        assert client.put(f"/api/opportunities/{oid}", headers=who, json=post_body(title="Hijacked")).status_code == 403
        assert client.delete(f"/api/opportunities/{oid}", headers=who).status_code == 403
    assert client.delete(f"/api/opportunities/{oid}").status_code == 401
    assert next(x for x in board(client, a.headers)["items"] if x["id"] == oid)["title"] == "Edited title"
    assert client.delete(f"/api/opportunities/{oid}", headers=a.headers).json()["deleted"] is True
    assert oid not in ids(board(client, a.headers, status="all"))
    assert client.delete(f"/api/opportunities/{oid}", headers=a.headers).status_code == 404
    assert client.put(f"/api/opportunities/999999", headers=a.headers, json=post_body()).status_code == 404


def test_admin_can_edit_and_delete_anyones_post(client, auth, alumni):
    (a,) = alumni(1)
    oid = make_post(client, a.headers)
    assert client.put(f"/api/opportunities/{oid}", headers=auth, json=post_body(title="Fixed by admin")).status_code == 200
    item = next(x for x in board(client, auth)["items"] if x["id"] == oid)
    assert item["title"] == "Fixed by admin" and item["can_edit"] is True and item["mine"] is False
    assert item["posted_by"]["name"] == a.name                                        # the original poster is still credited
    assert client.delete(f"/api/opportunities/{oid}", headers=auth).status_code == 200


def test_editing_a_closed_post_keeps_its_date_but_a_new_past_date_is_refused(client, alumni):
    (a,) = alumni(1)
    oid = make_post(client, a.headers)
    past = when(-5)
    with db() as c:
        c.execute("UPDATE opportunities SET closing_date=? WHERE id=?", (past, oid))
    assert client.put(f"/api/opportunities/{oid}", headers=a.headers, json=post_body(title="Typo fixed", closing_date=past)).status_code == 200
    assert client.put(f"/api/opportunities/{oid}", headers=a.headers, json=post_body(closing_date=when(-2))).status_code == 422
    assert client.put(f"/api/opportunities/{oid}", headers=a.headers, json=post_body(closing_date=when(20))).status_code == 200      # reopen
    assert oid in ids(board(client, a.headers))


# ---------------------------------------------------------------- housekeeping
def test_actions_are_audited(client, auth, alumni):
    (a,) = alumni(1)
    oid = make_post(client, a.headers, title="Audited post")
    client.put(f"/api/opportunities/{oid}", headers=a.headers, json=post_body(title="Audited post v2"))
    client.delete(f"/api/opportunities/{oid}", headers=auth)
    rows = client.get("/api/audit-logs", headers=auth, params={"entity_type": "opportunity", "page_size": 50}).json()["items"]
    got = {r["action"]: r for r in rows if str(r["entity_id"]) == str(oid)}
    assert {"opportunity.create", "opportunity.update", "opportunity.delete"} <= set(got)
    assert got["opportunity.delete"]["detail"]["by_owner"] is False


def test_posts_by_an_alumnus_are_removed_with_their_record(client, auth, alumni):
    a, b = alumni(2)
    mine, theirs = make_post(client, a.headers), make_post(client, b.headers)
    assert client.delete(f"/api/alumni/{a.aid}", headers=auth).status_code == 200
    with db() as c:
        left = {r["id"] for r in c.execute("SELECT id FROM opportunities")}
    assert mine not in left and theirs in left


def test_html_in_a_post_is_stored_as_plain_text(client, alumni):
    (a,) = alumni(1)
    oid = make_post(client, a.headers, title="<script>alert(1)</script> role", description="<img src=x onerror=alert(1)> hello there")
    item = next(i for i in board(client, a.headers)["items"] if i["id"] == oid)
    assert item["title"].startswith("<script>") and "<img" in item["description"]        # returned verbatim as data; the page renders text only
