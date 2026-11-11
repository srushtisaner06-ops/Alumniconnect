"""Phase 1B: career timeline, structured profile, member directory, invites, proof reminders."""
import itertools
import sqlite3

import pytest

from app import careers, config, profiles
from app import db as dbmod
from app.db import db

PDF = b"%PDF-1.4\n%proof\n"
_PRN = itertools.count(45000001)
EMP = {"company": "Acme Corp", "designation": "Engineer", "industry": "IT"}
HS = {"university": "MIT", "country": "USA", "degree": "MS", "specialization": "AI"}
ENT = {"startup_name": "Nimbus", "business_domain": "SaaS", "stage": "Idea"}


@pytest.fixture
def person(client, auth, import_people):
    def make():
        n = next(_PRN)
        aid = list(import_people([(f"Taylor Person{n}", n)], year=2044).values())[0]
        tok = client.get(f"/api/alumni/{aid}", headers=auth).json()["link"].split("token=")[1]
        return aid, tok
    return make


def submit(client, tok, career="EMPLOYMENT", details=EMP):
    r = client.post("/api/public/submit", json={"token": tok, "career_status": career, "details": details})
    assert r.status_code == 200, r.text


def events(client, auth, aid, live=True):
    ev = client.get(f"/api/alumni/{aid}", headers=auth).json()["career_events"]
    return [e for e in ev if not e["retracted"]] if live else ev


def kinds(client, auth, aid):
    return sorted(e["event_type"] for e in events(client, auth, aid))


# ---------------------------------------------------------------- timeline: written by the system
def test_import_writes_graduation_and_first_job_once(client, auth, import_people, person):
    aid, _ = person()
    ev = {e["event_type"]: e for e in events(client, auth, aid)}
    assert set(ev) == {"GRADUATION", "FIRST_JOB"}
    assert ev["GRADUATION"]["event_date"] == "2044" and ev["FIRST_JOB"]["organisation"] == "Acme Corp" and ev["FIRST_JOB"]["title"] == "Engineer"
    prn = int(client.get(f"/api/alumni/{aid}", headers=auth).json()["prn"])
    import_people([("Taylor Again", prn)], year=2044)                      # the same person imported again
    assert kinds(client, auth, aid) == ["FIRST_JOB", "GRADUATION"]          # nothing duplicated


def test_form_changes_become_the_right_events(client, auth, person):
    aid, tok = person()
    submit(client, tok)                                                     # same employer, same role: nothing new
    assert kinds(client, auth, aid) == ["FIRST_JOB", "GRADUATION"]
    submit(client, tok, details={**EMP, "designation": "Senior Engineer"})
    promo = next(e for e in events(client, auth, aid) if e["event_type"] == "PROMOTION")
    assert promo["detail"] == "Designation changed from Engineer to Senior Engineer"
    submit(client, tok, details={"company": "Globex", "designation": "Lead", "industry": "IT"})
    change = next(e for e in events(client, auth, aid) if e["event_type"] == "JOB_CHANGE")
    assert change["organisation"] == "Globex" and change["detail"] == "Moved from Acme Corp"
    submit(client, tok, details={"company": "Globex", "designation": "Lead", "industry": "IT"})   # repeating changes nothing
    assert kinds(client, auth, aid).count("JOB_CHANGE") == 1 and kinds(client, auth, aid).count("PROMOTION") == 1


def test_studies_and_venture_events_are_added_once(client, auth, person):
    aid, tok = person()
    for _ in range(2):
        submit(client, tok, "HIGHER_STUDIES", HS)
        submit(client, tok, "ENTREPRENEURSHIP", ENT)
    k = kinds(client, auth, aid)
    assert k.count("HIGHER_STUDIES") == 1 and k.count("ENTREPRENEURSHIP") == 1


def test_form_fills_blank_profile_fields_but_never_overwrites(client, auth, account, person):
    aid, tok = person()
    submit(client, tok)
    p = client.get(f"/api/alumni/{aid}", headers=auth).json()["profile"]
    assert p["designation"] == "Engineer" and p["professional_domain"] == "IT"
    owner = account("ALUMNI", aid)
    client.put("/api/profile/me/details", headers=owner.headers, json={"designation": "Principal Engineer"})
    submit(client, tok, details={**EMP, "designation": "Staff Engineer", "industry": "Fintech"})
    p = client.get(f"/api/alumni/{aid}", headers=auth).json()["profile"]
    assert p["designation"] == "Principal Engineer" and p["professional_domain"] == "IT"


# ---------------------------------------------------------------- timeline: added by people
def test_owner_and_staff_can_add_events_and_input_is_validated(client, auth, account, person):
    aid, _ = person()
    owner = account("ALUMNI", aid)
    ok = client.post("/api/profile/me/career-events", headers=owner.headers,
                     json={"event_type": "ACHIEVEMENT", "title": "Won the national hackathon", "event_date": "2025-03"})
    assert ok.status_code == 200
    assert client.post(f"/api/alumni/{aid}/career-events", headers=auth,
                       json={"event_type": "PROMOTION", "title": "Senior Engineer", "organisation": "Acme Corp", "event_date": "2026-01-15"}).status_code == 200
    bad = [{"event_type": "GRADUATION", "title": "x"}, {"event_type": "NOPE", "title": "x"}, {"event_type": "ACHIEVEMENT", "title": "  "},
           {"event_type": "ACHIEVEMENT", "title": "x", "event_date": "03/2025"}, {"event_type": "ACHIEVEMENT", "title": "x", "event_date": "2025-13"},
           {"event_type": "ACHIEVEMENT", "title": "x", "event_date": "1950"}, {"event_type": "ACHIEVEMENT", "title": "x", "event_date": "2999-01"},
           {"event_type": "ACHIEVEMENT", "title": "x" * 151}]
    for body in bad:
        assert client.post("/api/profile/me/career-events", headers=owner.headers, json=body).status_code == 422, body
    assert client.post("/api/profile/me/career-events", headers=account("STUDENT").headers,
                       json={"event_type": "ACHIEVEMENT", "title": "x"}).status_code == 403


def test_the_timeline_is_append_only_even_for_raw_sql(client, auth, person):
    aid, _ = person()
    eid = events(client, auth, aid)[0]["id"]
    for sql in ("UPDATE career_events SET title='rewritten' WHERE id=?", "UPDATE career_events SET event_date='1999' WHERE id=?",
                "UPDATE career_events SET created_by='someone' WHERE id=?"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            with db() as c:
                c.execute(sql, (eid,))


def test_retracting_keeps_history_and_hides_it_from_members(client, auth, account, person):
    aid, _ = person()
    owner = account("ALUMNI", aid)
    client.put("/api/profile/me/visibility", headers=owner.headers, json={"level": "PUBLIC"})
    eid = client.post("/api/profile/me/career-events", headers=owner.headers, json={"event_type": "ACHIEVEMENT", "title": "Typo award"}).json()["id"]
    assert client.post(f"/api/profile/me/career-events/{eid}/retract", headers=owner.headers, json={"reason": "x"}).status_code == 422
    assert client.post(f"/api/profile/me/career-events/{eid}/retract", headers=owner.headers, json={"reason": "Entered by mistake"}).status_code == 200
    assert client.post(f"/api/profile/me/career-events/{eid}/retract", headers=owner.headers, json={"reason": "Again"}).status_code == 409
    row = next(e for e in events(client, auth, aid, live=False) if e["id"] == eid)
    assert row["retracted"] and row["retract_reason"] == "Entered by mistake" and row["retracted_by"] == owner.email
    assert "Typo award" not in client.get(f"/api/profiles/{aid}").text                       # members never see it
    assert "Typo award" in client.get("/api/profile/me", headers=owner.headers).text         # the owner still does, struck through


def test_nobody_can_retract_someone_elses_event_or_graduation(client, auth, account, person):
    a, _ = person()
    b, _ = person()
    eid = client.post(f"/api/alumni/{b}/career-events", headers=auth, json={"event_type": "ACHIEVEMENT", "title": "B's award"}).json()["id"]
    owner_a = account("ALUMNI", a)
    assert client.post(f"/api/profile/me/career-events/{eid}/retract", headers=owner_a.headers, json={"reason": "not mine"}).status_code == 404
    grad = next(e for e in events(client, auth, a) if e["event_type"] == "GRADUATION")
    assert client.post(f"/api/alumni/{a}/career-events/{grad['id']}/retract", headers=auth, json={"reason": "wrong year"}).status_code == 409


# ---------------------------------------------------------------- profile fields
def test_owner_saves_a_profile_and_partial_updates_keep_the_rest(client, account, person):
    aid, _ = person()
    me = account("ALUMNI", aid)
    r = client.put("/api/profile/me/details", headers=me.headers, json={
        "whatsapp": "98765 43210", "country": "India", "city": "Pune", "professional_domain": "Data", "years_experience": 3.5,
        "headline": "Data engineer", "linkedin_url": "linkedin.com/in/taylor", "github_url": "https://github.com/taylor",
        "skills": ["Python", "python", "SQL", "Spark"], "interests": ["Hiking", "Open source"]})
    assert r.status_code == 200
    p = r.json()
    assert p["whatsapp"] == "+919876543210" and p["linkedin_url"] == "https://linkedin.com/in/taylor"
    assert p["skills"] == ["Python", "Spark", "SQL"]                                           # case-insensitive de-dupe, sorted
    again = client.put("/api/profile/me/details", headers=me.headers, json={"city": "Mumbai"}).json()
    assert again["city"] == "Mumbai" and again["country"] == "India" and again["skills"] == ["Python", "Spark", "SQL"]
    cleared = client.put("/api/profile/me/details", headers=me.headers, json={"city": "", "skills": []}).json()
    assert cleared["city"] is None and cleared["skills"] == []


@pytest.mark.parametrize("body", [
    {"whatsapp": "12345"}, {"whatsapp": "abc"}, {"years_experience": -1}, {"years_experience": 99}, {"years_experience": "many"},
    {"linkedin_url": "https://evil.example.com/in/x"}, {"github_url": "https://linkedin.com/x"}, {"portfolio_url": "http://plain.example.com"},
    {"portfolio_url": "https://localhost/x"}, {"portfolio_url": "https://127.0.0.1/x"}, {"portfolio_url": "https://user:pw@site.example.com"},
    {"portfolio_url": "javascript:alert(1)"}, {"skills": ["<script>"]}, {"skills": ["x" * 41]}, {"skills": [f"s{i}" for i in range(31)]},
    {"city": "x" * 81}], ids=lambda b: next(iter(b)) + ":" + str(next(iter(b.values())))[:14])
def test_profile_input_is_validated(client, account, person, body):
    me = account("ALUMNI", person()[0])
    assert client.put("/api/profile/me/details", headers=me.headers, json=body).status_code == 422


def test_only_the_owner_or_staff_can_change_a_profile(client, auth, account, person):
    a, _ = person()
    b, _ = person()
    other = account("ALUMNI", b)
    assert client.put(f"/api/alumni/{a}/profile", headers=other.headers, json={"city": "Delhi"}).status_code == 403
    assert client.put("/api/profile/me/details", headers=account("STUDENT").headers, json={"city": "Delhi"}).status_code == 403
    assert client.put(f"/api/alumni/{a}/profile", headers=account("FACULTY").headers, json={"city": "Delhi"}).status_code == 200
    assert client.put("/api/alumni/99999999/profile", headers=auth, json={"city": "Delhi"}).status_code == 404


def test_whatsapp_is_never_shown_to_other_members(client, auth, account, person):
    aid, _ = person()
    me = account("ALUMNI", aid)
    client.put("/api/profile/me/details", headers=me.headers, json={"whatsapp": "+919876543210", "city": "Pune", "skills": ["Go"]})
    client.put("/api/profile/me/visibility", headers=me.headers, json={"level": "PUBLIC"})
    for headers in ({}, account("STUDENT").headers):
        body = client.get(f"/api/profiles/{aid}", headers=headers).json()
        assert body["profile"]["city"] == "Pune" and body["profile"]["skills"] == ["Go"]
        assert "whatsapp" not in body["profile"] and "9876543210" not in str(body)
    assert client.get("/api/profile/me", headers=me.headers).json()["profile"]["whatsapp"] == "+919876543210"
    assert client.get(f"/api/alumni/{aid}", headers=auth).json()["profile"]["whatsapp"] == "+919876543210"


def test_profile_audit_records_field_names_not_values(client, auth, account, person):
    aid, _ = person()
    client.put("/api/profile/me/details", headers=account("ALUMNI", aid).headers, json={"city": "Secretville", "whatsapp": "+919876543210"})
    row = client.get("/api/audit-logs", headers=auth, params={"action": "profile.update", "entity_id": aid}).json()["items"][0]
    assert row["detail"] == {"fields": ["city", "whatsapp"]} and "Secretville" not in str(row)


# ---------------------------------------------------------------- directory
def test_directory_shows_each_viewer_only_what_they_may_see(client, auth, account, person):
    (a, _), (b, _), (c, _), (d, _) = person(), person(), person(), person()
    ob, oc, od = account("ALUMNI", b), account("ALUMNI", c), account("ALUMNI", d)
    client.put("/api/profile/me/visibility", headers=ob.headers, json={"level": "ALUMNI_ONLY"})
    client.put("/api/profile/me/visibility", headers=oc.headers, json={"level": "PUBLIC"})        # a stays PRIVATE (default)
    stu = account("STUDENT")
    ids = lambda who, **q: {i["id"] for i in client.get("/api/directory", headers=who.headers if hasattr(who, "headers") else who,
                                                       params={"page_size": 60, "search": "Taylor Person", **q}).json()["items"]}
    assert c in ids(stu) and b not in ids(stu) and a not in ids(stu)
    assert {b, c} <= ids(od) and a not in ids(od) and d in ids(od)                                # alumni also see themself
    assert {a, b, c} <= ids(auth)                                         # staff: everything, in the member view
    staff_item = next(i for i in client.get("/api/directory", headers=auth, params={"page_size": 60, "search": "Taylor Person"}).json()["items"] if i["id"] == a)
    assert set(staff_item) == {"id", "name", "graduation_year", "career_status", "organisations", "profile", "timeline"}
    assert client.get("/api/directory").status_code == 401


def test_directory_search_covers_skills_organisations_and_places(client, account, person):
    aid, _ = person()
    me = account("ALUMNI", aid)
    client.put("/api/profile/me/visibility", headers=me.headers, json={"level": "PUBLIC"})
    client.put("/api/profile/me/details", headers=me.headers, json={"city": "Nagpurville", "skills": ["Zymurgy"], "professional_domain": "Brewing"})
    stu = account("STUDENT")
    for term in ("Zymurgy", "Nagpurville", "Brewing", "Acme Corp", "Taylor Person"):
        found = client.get("/api/directory", headers=stu.headers, params={"search": term, "page_size": 60}).json()["items"]
        assert aid in {i["id"] for i in found}, term
    assert aid not in {i["id"] for i in client.get("/api/directory", headers=stu.headers, params={"search": "zzz-no-match"}).json()["items"]}


def test_directory_paginates(client, account, person):
    for _ in range(3):
        aid, _t = person()
        client.put("/api/profile/me/visibility", headers=account("ALUMNI", aid).headers, json={"level": "PUBLIC"})
    stu = account("STUDENT")
    p1 = client.get("/api/directory", headers=stu.headers, params={"page_size": 2, "page": 1}).json()
    p2 = client.get("/api/directory", headers=stu.headers, params={"page_size": 2, "page": 2}).json()
    assert len(p1["items"]) == 2 and p1["total"] >= 3 and {i["id"] for i in p1["items"]}.isdisjoint({i["id"] for i in p2["items"]})


# ---------------------------------------------------------------- invites
def test_invite_lets_the_person_choose_their_own_password(client, auth, person):
    aid, _ = person()
    r = client.post("/api/users", headers=auth, json={"email": "invitee1@example.com", "role": "ALUMNI", "alumni_id": aid}).json()
    assert r["invited"] is True and r["emailed"] is False and "/reset-password?token=" in r["invite_link"]     # no SMTP in tests
    assert client.post("/api/auth/login", json={"email": "invitee1@example.com", "password": "anything"}).status_code == 401
    token = r["invite_link"].split("token=")[1]
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "weak"}).status_code == 422
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "Chosen-Pass-77"}).status_code == 200
    login = client.post("/api/auth/login", json={"email": "invitee1@example.com", "password": "Chosen-Pass-77"})
    assert login.status_code == 200 and login.json()["role"] == "ALUMNI"


def test_invite_links_expire_and_work_once(client, auth, person):
    aid, _ = person()
    link = client.post("/api/users", headers=auth, json={"email": "invitee2@example.com", "role": "ALUMNI", "alumni_id": aid}).json()["invite_link"]
    token = link.split("token=")[1]
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "Chosen-Pass-77"}).status_code == 200
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "Chosen-Pass-88"}).status_code == 400
    aid2, _ = person()
    t2 = client.post("/api/users", headers=auth, json={"email": "invitee3@example.com", "role": "ALUMNI", "alumni_id": aid2}).json()["invite_link"].split("token=")[1]
    with db() as c:
        c.execute("UPDATE password_resets SET expires_at='2000-01-01 00:00:00'")
    assert client.post("/api/auth/password-reset/confirm", json={"token": t2, "new_password": "Chosen-Pass-77"}).status_code == 400


def test_a_typed_password_still_works_and_returns_no_link(client, auth):
    r = client.post("/api/users", headers=auth, json={"email": "typed1@example.com", "role": "STUDENT", "password": "Str0ng-Pass-1"}).json()
    assert r["invited"] is False and "invite_link" not in r


def test_only_admins_see_whether_an_alumnus_has_a_login(client, auth, account, person):
    aid, _ = person()
    assert client.get(f"/api/alumni/{aid}", headers=auth).json()["account"] is None
    account("ALUMNI", aid)
    assert client.get(f"/api/alumni/{aid}", headers=auth).json()["account"]["role"] == "ALUMNI"
    assert "account" not in client.get(f"/api/alumni/{aid}", headers=account("FACULTY").headers).json()


# ---------------------------------------------------------------- proof reminders
def _upload(client, tok):
    return client.post("/api/public/proof", data={"token": tok, "career_status": "EMPLOYMENT", "doc_type": "JOINING_MAIL"},
                       files={"file": ("m.pdf", PDF, "application/pdf")})


def _proof_group(client, auth, person):
    (a, ta), (b, tb), (c_, tc), (d, td) = person(), person(), person(), person()
    for t in (ta, tb, tc):
        submit(client, t)                                              # a, b, c have submitted; d has not
    _upload(client, tb)                                                # b: proof pending
    doc = _upload(client, tc).json()["proof"]["id"]                    # c: proof rejected
    client.post(f"/api/documents/{doc}/review", headers=auth, json={"decision": "REJECTED", "reason": "The image is too dark"})
    return a, b, c_, d, ta


def test_proof_preview_buckets_and_targeting(client, auth, person):
    a, b, c_, d, _ = _proof_group(client, auth, person)
    sel = {"alumni_ids": [a, b, c_, d]}
    pv = client.post("/api/recipients/preview", headers=auth, json={"recipients": sel, "channel": "email", "purpose": "PROOF"}).json()
    assert pv["selected"] == 4 and pv["eligible"] == 2 and pv["completed"] == 1 and pv["not_submitted"] == 1
    normal = client.post("/api/recipients/preview", headers=auth, json={"recipients": sel, "channel": "email"}).json()
    assert "not_submitted" not in normal and normal["eligible"] == 1 and normal["completed"] == 3     # the original behaviour, unchanged


def test_proof_campaign_reaches_only_people_who_need_it_and_counts_its_own_attempts(client, auth, person):
    a, b, c_, d, ta = _proof_group(client, auth, person)
    body = {"name": "Proof round", "purpose": "PROOF", "max_attempts": 3, "interval_hours": 0.01, "recipients": {"alumni_ids": [a, b, c_, d]}}
    cid = client.post("/api/campaigns", headers=auth, json=body).json()["id"]
    camp = lambda: next(x for x in client.get("/api/campaigns", headers=auth).json()["items"] if x["id"] == cid)
    assert camp()["purpose"] == "PROOF" and camp()["reachable"] == 2
    client.post(f"/api/campaigns/{cid}/start", headers=auth)
    assert client.post(f"/api/campaigns/{cid}/run-now", headers=auth).json()["simulated"] == 2
    logged = {r["alumni_id"] for r in client.get("/api/reminders", headers=auth, params={"campaign_id": cid}).json()["items"] if r["status"] == "SIMULATED"}
    assert logged == {a, c_}                                           # not b (has a proof), not d (has not submitted)
    assert client.get(f"/api/alumni/{a}", headers=auth).json()["reminders_sent"] == 0      # the person's update-reminder counter is untouched
    with db() as c:
        c.execute("UPDATE campaigns SET interval_hours=0 WHERE id=?", (cid,))
    _upload(client, ta)                                                # a uploads a proof...
    assert client.post(f"/api/campaigns/{cid}/run-now", headers=auth).json()["simulated"] == 1        # ...so only c is reminded again
    attempts = sorted(r["attempt"] for r in client.get("/api/reminders", headers=auth, params={"campaign_id": cid}).json()["items"] if r["alumni_id"] == c_ and r["status"] == "SIMULATED")
    assert attempts == [1, 2]


def test_proof_campaign_stops_after_max_attempts_and_purpose_cannot_change(client, auth, person):
    a, *_ = _proof_group(client, auth, person)
    body = {"name": "One shot", "purpose": "PROOF", "max_attempts": 1, "interval_hours": 0.01, "recipients": {"alumni_ids": [a]}}
    cid = client.post("/api/campaigns", headers=auth, json=body).json()["id"]
    client.post(f"/api/campaigns/{cid}/start", headers=auth)
    client.post(f"/api/campaigns/{cid}/run-now", headers=auth)
    assert next(x for x in client.get("/api/campaigns", headers=auth).json()["items"] if x["id"] == cid)["status"] == "COMPLETED"
    assert client.put(f"/api/campaigns/{cid}", headers=auth, json={**body, "purpose": "UPDATE"}).status_code == 409
    assert client.post("/api/campaigns", headers=auth, json={**body, "purpose": "NONSENSE"}).status_code == 422


# ---------------------------------------------------------------- lifecycle
def test_undo_brings_back_profile_and_timeline(client, auth, account, person):
    aid, _ = person()
    me = account("ALUMNI", aid)
    client.put("/api/profile/me/details", headers=me.headers, json={"city": "Pune", "skills": ["Rust"]})
    eid = client.post("/api/profile/me/career-events", headers=me.headers, json={"event_type": "ACHIEVEMENT", "title": "Gold medal"}).json()["id"]
    before = client.get(f"/api/alumni/{aid}", headers=auth).json()
    client.delete(f"/api/alumni/{aid}", headers=auth)
    with db() as c:
        assert c.execute("SELECT COUNT(*) n FROM career_events WHERE alumni_id=?", (aid,)).fetchone()["n"] == 0      # erased with the person
        assert c.execute("SELECT COUNT(*) n FROM profiles WHERE alumni_id=?", (aid,)).fetchone()["n"] == 0
    assert client.post("/api/undo", headers=auth).status_code == 200
    after = client.get(f"/api/alumni/{aid}", headers=auth).json()
    assert after["profile"]["city"] == "Pune" and after["profile"]["skills"] == ["Rust"]
    assert [e["id"] for e in after["career_events"]] == [e["id"] for e in before["career_events"]] and eid in {e["id"] for e in after["career_events"]}


def test_migration_backfills_timeline_for_existing_people_and_is_repeatable(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    old = sqlite3.connect(path)
    old.executescript(dbmod.SCHEMA)
    old.execute("INSERT INTO users(email,password_hash) VALUES('boss@x.edu','h')")
    old.execute("INSERT INTO alumni(id,name,prn,graduation_year,token,status,career_status,details) VALUES(1,'Old Timer','11111111',2019,'tok1','COMPLETED','EMPLOYMENT',"
                "'{\"company\":\"Initech\",\"designation\":\"Analyst\",\"industry\":\"Finance\"}')")
    old.execute("INSERT INTO offers(alumni_id,employer,package_lpa,position) VALUES(1,'Initech',9.0,'Analyst')")
    old.execute("INSERT INTO alumni(id,name,prn,graduation_year,token) VALUES(2,'Studier','22222222',2020,'tok2')")
    old.execute("INSERT INTO higher_studies(alumni_id,degree,institution) VALUES(2,'MS','ETH Zurich')")
    old.commit(); old.close()
    monkeypatch.setattr(config, "DB_PATH", str(path))
    dbmod.init(); dbmod.init()
    with db() as c:
        ev = lambda aid: sorted((e["event_type"], e["organisation"]) for e in careers.list_events(c, aid))
        assert ev(1) == [("FIRST_JOB", "Initech"), ("GRADUATION", None)]
        assert ev(2) == [("GRADUATION", None), ("HIGHER_STUDIES", "ETH Zurich")]
        assert profiles.get(c, 1)["designation"] == "Analyst" and profiles.get(c, 1)["professional_domain"] == "Finance"
        careers.baseline(c, 1)
        careers.baseline(c, 2)                                          # running it again adds nothing
        assert len(careers.list_events(c, 1)) == 2 and len(careers.list_events(c, 2)) == 2
        assert [r["version"] for r in c.execute("SELECT version FROM schema_migrations")] == [1, 2, 3]
