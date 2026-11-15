"""Phase 2: the small set of directory filters, shared by the staff directory, the member directory and the CSV export.

Keeping the rules in one place means "what you filtered" and "what you exported" can never drift apart.

Filters (all optional, all combined with AND):

  batch         graduation year
  career        PLACEMENT | HIGHER_STUDIES | ENTREPRENEURSHIP  (has at least one record of that kind)
  organisation  part of an employer / college / company name
  domain        professional domain, exact choice from the list `options()` returns (case-insensitive)

Sorting: name, name_desc, year, year_desc. Every sort ends with the name and id, so pages never shuffle.

Every SQL fragment here uses the alias `a` for the alumni table and only ever binds user input as parameters.
"""

CAREER_TABLES = {"PLACEMENT": "offers", "HIGHER_STUDIES": "higher_studies", "ENTREPRENEURSHIP": "ventures"}

SORTS = {
    "name": "a.name COLLATE NOCASE ASC, a.id ASC",
    "name_desc": "a.name COLLATE NOCASE DESC, a.id ASC",
    "year": "a.graduation_year ASC, a.name COLLATE NOCASE ASC, a.id ASC",
    "year_desc": "a.graduation_year DESC, a.name COLLATE NOCASE ASC, a.id ASC",
}


class FilterError(ValueError):
    """A filter value that is not allowed. Routes turn this into a 422."""


def order_by(sort, default="name"):
    key = (sort or "").strip() or default
    if key not in SORTS:
        raise FilterError("sort must be one of " + ", ".join(SORTS))
    return SORTS[key]


def career_value(career):
    career = (career or "").strip().upper()
    if career in ("", "ALL"):
        return None
    if career not in CAREER_TABLES:
        raise FilterError("career must be all|" + "|".join(CAREER_TABLES))
    return career


def _like(term):
    """LIKE pattern for a partial match. % and _ typed by the user are matched literally (pair with ESCAPE '\\')."""
    t = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


def conditions(batch=None, career=None, organisation="", domain=""):
    """-> (list of SQL conditions, list of args) for the Phase 2 filters. Empty filters add nothing."""
    where, args = [], []
    if batch:
        where.append("a.graduation_year=?")
        args.append(int(batch))
    career = career_value(career)
    if career:
        where.append(f"EXISTS (SELECT 1 FROM {CAREER_TABLES[career]} t WHERE t.alumni_id=a.id)")
    org = (organisation or "").strip()
    if org:
        like = _like(org)
        where.append("(EXISTS (SELECT 1 FROM offers o WHERE o.alumni_id=a.id AND o.employer LIKE ? ESCAPE '\\')"
                     " OR EXISTS (SELECT 1 FROM higher_studies h WHERE h.alumni_id=a.id AND h.institution LIKE ? ESCAPE '\\')"
                     " OR EXISTS (SELECT 1 FROM ventures v WHERE v.alumni_id=a.id AND v.company LIKE ? ESCAPE '\\'))")
        args += [like, like, like]
    dom = (domain or "").strip()
    if dom:
        where.append("EXISTS (SELECT 1 FROM profiles p WHERE p.alumni_id=a.id AND LOWER(TRIM(p.professional_domain))=LOWER(?))")
        args.append(dom)
    return where, args


def options(c, scope_sql="1", scope_args=()):
    """Values for the filter dropdowns, limited to the people the caller may see.

    `scope_sql` is a condition over `a` (alumni) and `v` (profile_visibility, LEFT JOINed). Staff pass the default (everyone);
    the member directory passes its visibility rule, so a private profile never leaks its batch or domain into the lists.
    """
    base = f"FROM alumni a LEFT JOIN profile_visibility v ON v.alumni_id=a.id WHERE {scope_sql}"
    batches = [r["y"] for r in c.execute(f"SELECT DISTINCT a.graduation_year y {base} ORDER BY y DESC", list(scope_args))]
    domains = [r["d"] for r in c.execute(
        f"SELECT MIN(TRIM(p.professional_domain)) d FROM alumni a LEFT JOIN profile_visibility v ON v.alumni_id=a.id "
        f"JOIN profiles p ON p.alumni_id=a.id WHERE {scope_sql} AND TRIM(COALESCE(p.professional_domain,''))<>'' "
        f"GROUP BY LOWER(TRIM(p.professional_domain)) ORDER BY d COLLATE NOCASE", list(scope_args))]
    return {"batches": batches, "domains": domains, "careers": list(CAREER_TABLES)}
