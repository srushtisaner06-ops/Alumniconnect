"""Phase 2: directory filters, sorting, filtered CSV export and the domain chart data."""
import csv
import io
import itertools

import pytest

from app.db import db

_PRN = itertools.count(46000001)
_YEAR = itertools.count(2061)          # a fresh graduation year per test keeps every test independent of the others


def _batch(import_people, names):
    """Import `names` as one new batch. -> (year, {name: alumni_id})."""
    year = next(_YEAR)
    people = [(n, next(_PRN)) for n in names]
    ids = import_people(people, year=year)
    return year, {n: ids[prn] for n, prn in people}


def _set_domain(client, auth, aid, domain):
    r = client.put(f"/api/alumni/{aid}/profile", headers=auth, json={"professional_domain": domain})
    assert r.status_code == 200, r.text


def _add_higher_studies(aid, institution="Zeta University"):
    with db() as c:
        c.execute("INSERT INTO higher_studies(alumni_id,degree,institution) VALUES(?,?,?)", (aid, "MS", institution))


def _public(client, account, aid):
    client.put("/api/profile/me/visibility", headers=account("ALUMNI", aid).headers, json={"level": "PUBLIC"})


def _names(resp):
    assert resp.status_code == 200, resp.text
    return [i["name"] for i in resp.json()["items"]]


# ---------------------------------------------------------------- staff directory
def test_staff_filters_by_batch_career_organisation_and_domain(client, auth, import_people):
    year, ids = _batch(import_people, ["Ann Filter", "Bob Filter", "Cy Filter"])
    _add_higher_studies(ids["Bob Filter"])                       # Bob has placement (import) and higher studies
    _set_domain(client, auth, ids["Ann Filter"], "Data Science")
    _set_domain(client, auth, ids["Cy Filter"], "  data science ")      # same domain, different case / spacing

    base = {"batch": year, "page_size": 100}
    get = lambda **q: _names(client.get("/api/alumni", headers=auth, params={**base, **q}))
    assert sorted(get()) == ["Ann Filter", "Bob Filter", "Cy Filter"]
    assert get(category="HIGHER_STUDIES") == ["Bob Filter"]
    assert sorted(get(category="PLACEMENT")) == ["Ann Filter", "Bob Filter", "Cy Filter"]
    assert get(organisation="zeta univ") == ["Bob Filter"]                       # college names are searched too
    assert sorted(get(organisation="acme")) == ["Ann Filter", "Bob Filter", "Cy Filter"]
    assert sorted(get(domain="DATA SCIENCE")) == ["Ann Filter", "Cy Filter"]    # exact choice, ignoring case
    assert get(domain="Data Science", category="HIGHER_STUDIES") == []           # filters combine with AND
    assert get(batch=year + 500 if year + 500 <= 2100 else 2100) == []
    assert client.get("/api/alumni", headers=auth, params={"organisation": "100%"}).json()["total"] == 0   # % is literal, not a wildcard


def test_staff_sort_by_name_and_year(client, auth, import_people):
    year, _ = _batch(import_people, ["Zed Sorted", "Amy Sorted", "Mia Sorted"])
    q = {"batch": year, "page_size": 100}
    assert _names(client.get("/api/alumni", headers=auth, params={**q, "sort": "name"})) == ["Amy Sorted", "Mia Sorted", "Zed Sorted"]
    assert _names(client.get("/api/alumni", headers=auth, params={**q, "sort": "name_desc"})) == ["Zed Sorted", "Mia Sorted", "Amy Sorted"]
    y2, _ = _batch(import_people, ["Old Sorted"])
    both = client.get("/api/alumni", headers=auth, params={"search": "Sorted", "page_size": 100, "sort": "year_desc"}).json()["items"]
    years = [i["graduation_year"] for i in both]
    assert years == sorted(years, reverse=True) and years[0] == y2
    asc = client.get("/api/alumni", headers=auth, params={"search": "Sorted", "page_size": 100, "sort": "year"}).json()["items"]
    assert [i["graduation_year"] for i in asc] == sorted(years)


def test_bad_filter_values_are_rejected(client, auth):
    assert client.get("/api/alumni", headers=auth, params={"sort": "salary"}).status_code == 422
    assert client.get("/api/alumni", headers=auth, params={"category": "NOPE"}).status_code == 422
    assert client.get("/api/directory", headers=auth, params={"sort": "salary"}).status_code == 422
    assert client.get("/api/directory", headers=auth, params={"career": "NOPE"}).status_code == 422
    assert client.get("/api/alumni/export", headers=auth, params={"sort": "salary"}).status_code == 422


def test_staff_filter_options_list_batches_and_domains(client, auth, import_people, account):
    year, ids = _batch(import_people, ["Opt One"])
    _set_domain(client, auth, ids["Opt One"], "Quantum Basketry")
    opts = client.get("/api/alumni/filters", headers=auth).json()
    assert year in opts["batches"] and opts["batches"] == sorted(opts["batches"], reverse=True)
    assert "Quantum Basketry" in opts["domains"]
    assert client.get("/api/alumni/filters", headers=account("STUDENT").headers).status_code == 403
    assert client.get("/api/alumni/filters").status_code == 401


# ---------------------------------------------------------------- filtered export
def _csv_rows(resp):
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))


def test_export_contains_exactly_the_filtered_rows_from_every_page(client, auth, import_people):
    year, ids = _batch(import_people, [f"Exp Person{i:02d}" for i in range(30)])    # more than one page of 25
    _set_domain(client, auth, ids["Exp Person03"], "Rocketry")
    _set_domain(client, auth, ids["Exp Person07"], "Rocketry")
    rows = _csv_rows(client.get("/api/alumni/export", headers=auth, params={"batch": year}))
    assert rows[0][:3] == ["Sr No", "Name", "PRN"] and len(rows) == 1 + 30          # all pages, not just the first 25
    rows = _csv_rows(client.get("/api/alumni/export", headers=auth, params={"batch": year, "domain": "rocketry", "sort": "name_desc"}))
    head, body = rows[0], rows[1:]
    assert [r[head.index("Name")] for r in body] == ["Exp Person07", "Exp Person03"]
    assert {r[head.index("Professional domain")] for r in body} == {"Rocketry"}
    assert {r[head.index("Graduation Year")] for r in body} == {str(year)}
    assert body[0][head.index("Career status")] == "Placement" and body[0][head.index("Company / institution")] == "Acme Corp"


def test_export_matches_what_the_directory_list_shows(client, auth, import_people):
    year, ids = _batch(import_people, ["Same One", "Same Two", "Other Three"])
    _add_higher_studies(ids["Same Two"])
    params = {"batch": year, "category": "HIGHER_STUDIES", "search": "Same", "page_size": 100}
    listed = _names(client.get("/api/alumni", headers=auth, params=params))
    exported = [r[1] for r in _csv_rows(client.get("/api/alumni/export", headers=auth, params=params))[1:]]
    assert listed == exported == ["Same Two"]


def test_export_is_audited_with_its_filters_and_needs_permission(client, auth, import_people, account):
    year, ids = _batch(import_people, ["Audit Export"])
    client.get("/api/alumni/export", headers=auth, params={"batch": year, "category": "PLACEMENT"})
    row = client.get("/api/audit-logs", headers=auth, params={"action": "export.run", "entity_id": "directory"}).json()["items"][0]
    assert row["detail"]["rows"] == 1 and row["detail"]["filters"]["batch"] == year and row["detail"]["filters"]["category"] == "PLACEMENT"
    for who in (account("STUDENT"), account("ALUMNI", list(ids.values())[0])):
        assert client.get("/api/alumni/export", headers=who.headers).status_code == 403
    assert client.get("/api/alumni/export").status_code == 401


def test_export_neutralises_spreadsheet_formulas(client, auth, import_people):
    year, ids = _batch(import_people, ["Formula Person"])
    with db() as c:                       # the importer already rejects such names; this guards data that arrives any other way
        c.execute("UPDATE alumni SET name='=cmd Injection' WHERE id=?", (ids["Formula Person"],))
    rows = _csv_rows(client.get("/api/alumni/export", headers=auth, params={"batch": year}))
    assert rows[1][1] == "'=cmd Injection"


# ---------------------------------------------------------------- member directory
def test_member_filters_never_reveal_private_profiles(client, auth, account, import_people):
    year, ids = _batch(import_people, ["Vis Public", "Vis Private"])
    _set_domain(client, auth, ids["Vis Public"], "Cartography")
    _set_domain(client, auth, ids["Vis Private"], "Secret Cartography")
    _add_higher_studies(ids["Vis Private"], "Hidden College")
    _public(client, account, ids["Vis Public"])                                   # Vis Private stays PRIVATE
    stu = account("STUDENT")
    get = lambda **q: _names(client.get("/api/directory", headers=stu.headers, params={"batch": year, "page_size": 60, **q}))
    assert get() == ["Vis Public"]
    assert get(career="HIGHER_STUDIES") == []                                      # the private person's record is not reachable
    assert get(organisation="hidden college") == []
    assert get(domain="Secret Cartography") == []
    assert get(domain="cartography", career="PLACEMENT", organisation="acme") == ["Vis Public"]
    opts = client.get("/api/directory/filters", headers=stu.headers).json()
    assert "Cartography" in opts["domains"] and "Secret Cartography" not in opts["domains"] and year in opts["batches"]
    assert client.get("/api/directory/filters").status_code == 401
    # staff see everyone in the member view, so the private person's domain is available to them
    assert "Secret Cartography" in client.get("/api/directory/filters", headers=auth).json()["domains"]


def test_member_directory_sorting_and_unfiltered_default(client, auth, account, import_people):
    year, ids = _batch(import_people, ["Sort Zulu", "Sort Alpha"])
    for aid in ids.values():
        _public(client, account, aid)
    stu = account("STUDENT")
    q = {"batch": year, "page_size": 60}
    assert _names(client.get("/api/directory", headers=stu.headers, params=q)) == ["Sort Alpha", "Sort Zulu"]          # default: by name
    assert _names(client.get("/api/directory", headers=stu.headers, params={**q, "sort": "name_desc"})) == ["Sort Zulu", "Sort Alpha"]
    mixed = client.get("/api/directory", headers=stu.headers, params={"search": "Sort ", "page_size": 60, "sort": "year_desc"}).json()["items"]
    assert [i["graduation_year"] for i in mixed] == sorted((i["graduation_year"] for i in mixed), reverse=True)


# ---------------------------------------------------------------- dashboard analytics
def test_analytics_reports_alumni_by_domain(client, auth, import_people):
    _, ids = _batch(import_people, ["Dom One", "Dom Two", "Dom Three", "Dom Four"])
    for name, dom in (("Dom One", "Astro Farming"), ("Dom Two", "astro farming"), ("Dom Three", "Astro Farming ")):
        _set_domain(client, auth, ids[name], dom)
    for path in ("/api/dashboard", "/api/reports/analytics"):
        data = client.get(path, headers=auth).json()
        d = data["by_domain"]
        top = {r["domain"].lower(): r["alumni"] for r in d["items"]}
        assert top["astro farming"] == 3                                            # grouped regardless of case / spacing
        assert d["with_domain"] >= 3 and d["without_domain"] == data["summary"]["total"] - d["with_domain"]
        assert len(d["items"]) <= 8 and [r["alumni"] for r in d["items"]] == sorted((r["alumni"] for r in d["items"]), reverse=True)
        assert {"by_batch", "career", "progression"} <= set(data)                   # the earlier chart data is still there
