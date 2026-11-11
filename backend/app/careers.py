"""Career timeline: an append-only list of things that happened in a person's career.

  * Events are never edited or deleted. A mistake is *retracted* (kept, struck through, with who and why) and a correct
    event is added. The database enforces this with a trigger (migration 3), so no code path can quietly rewrite history.
  * Some events are written by the system from data we already hold (graduation year, placement / higher-studies /
    venture records, the form the alumnus submits). They are de-duplicated, so importing or submitting twice does not
    create two "first job" entries.
  * Dates may be a year, a month or a day ("2024", "2024-07", "2024-07-01"); many records only carry a year.
"""
import re
from datetime import datetime, timedelta, timezone

TYPES = {
    "GRADUATION": "Graduation", "FIRST_JOB": "First job", "JOB_CHANGE": "Job change", "PROMOTION": "Promotion",
    "HIGHER_STUDIES": "Higher studies", "ENTREPRENEURSHIP": "Entrepreneurship", "ACHIEVEMENT": "Achievement",
}
EMPLOYMENT_TYPES = ("FIRST_JOB", "JOB_CHANGE", "PROMOTION")
USER_TYPES = tuple(t for t in TYPES if t != "GRADUATION")        # graduation comes from the record, nobody adds it by hand
SOURCES = ("IMPORT", "FORM", "PROFILE", "STAFF", "MIGRATION")
_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


class CareerError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def clean_date(value):
    """'' / None -> None. Otherwise a valid YYYY, YYYY-MM or YYYY-MM-DD that is not more than a year ahead."""
    v = (value or "").strip()
    if not v:
        return None
    m = _DATE_RE.match(v)
    if not m:
        raise CareerError("Date must look like 2024, 2024-07 or 2024-07-15")
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    try:
        datetime(y, mo, d)
    except ValueError:
        raise CareerError("That date does not exist")
    if y < 1980 or datetime(y, mo, d) > datetime.now() + timedelta(days=366):
        raise CareerError("Date must be between 1980 and a year from now")
    return v


def _txt(value, limit, name, required=False):
    v = re.sub(r"\s+", " ", (value or "")).strip()
    if required and not v:
        raise CareerError(f"{name} is required")
    if len(v) > limit:
        raise CareerError(f"{name} must be at most {limit} characters")
    return v or None


# ---------------------------------------------------------------- write
def add_event(c, alumni_id, event_type, title, *, event_date=None, organisation=None, detail=None, source="STAFF", by=None,
              dedupe=False):
    """Append an event. With dedupe=True an identical live event (same type, title, organisation) is not added twice.
    Returns the new id, or None when it was a duplicate."""
    if event_type not in TYPES:
        raise CareerError("Unknown event type")
    if source not in SOURCES:
        raise CareerError("Unknown source")
    title = _txt(title, 150, "Title", required=True)
    org = _txt(organisation, 150, "Organisation")
    detail = _txt(detail, 1000, "Details")
    when = clean_date(event_date) if source in ("STAFF", "PROFILE") else (event_date or None)
    if dedupe and c.execute("SELECT 1 FROM career_events WHERE alumni_id=? AND event_type=? AND retracted_at IS NULL "
                            "AND lower(title)=lower(?) AND lower(COALESCE(organisation,''))=lower(?)",
                            (alumni_id, event_type, title, org or "")).fetchone():
        return None
    return c.execute("INSERT INTO career_events(alumni_id,event_type,event_date,title,organisation,detail,source,created_at,created_by) "
                     "VALUES(?,?,?,?,?,?,?,?,?)", (alumni_id, event_type, when, title, org, detail, source, _now(), by)).lastrowid


def retract(c, event_id, by, reason, alumni_id=None):
    """Strike an event out. `alumni_id` (when given) must match, so one person cannot retract another's event."""
    r = c.execute("SELECT * FROM career_events WHERE id=?", (event_id,)).fetchone()
    if not r or (alumni_id is not None and r["alumni_id"] != alumni_id):
        raise CareerError("Event not found", 404)
    if r["event_type"] == "GRADUATION":
        raise CareerError("Graduation comes from the student record and cannot be retracted here", 409)
    if r["retracted_at"]:
        raise CareerError("This event was already retracted", 409)
    reason = _txt(reason, 300, "Reason", required=True)
    if len(reason) < 3:
        raise CareerError("Give a short reason")
    c.execute("UPDATE career_events SET retracted_at=?, retracted_by=?, retract_reason=? WHERE id=?", (_now(), by, reason, event_id))
    return r["alumni_id"]


# ---------------------------------------------------------------- read
def _sort_key(e):
    return (e["event_date"] or e["created_at"][:10], e["id"])


def list_events(c, alumni_id, include_retracted=True):
    q = "SELECT * FROM career_events WHERE alumni_id=?" + ("" if include_retracted else " AND retracted_at IS NULL")
    out = []
    for r in c.execute(q, (alumni_id,)):
        d = dict(r)
        d["type_label"] = TYPES.get(d["event_type"], d["event_type"])
        d["retracted"] = bool(d["retracted_at"])
        out.append(d)
    return sorted(out, key=_sort_key)


def member_view(events):
    """What other members may see of a timeline: live events only, and nothing about who wrote or retracted them."""
    return [{"event_type": e["event_type"], "type_label": e["type_label"], "event_date": e["event_date"],
             "title": e["title"], "organisation": e["organisation"]} for e in events if not e["retracted"]]


# ---------------------------------------------------------------- events the system writes from data we already hold
def _has_type(c, aid, types):
    marks = ",".join("?" * len(types))
    return c.execute(f"SELECT 1 FROM career_events WHERE alumni_id=? AND retracted_at IS NULL AND event_type IN ({marks}) LIMIT 1",
                     (aid, *types)).fetchone() is not None


def baseline(c, aid, source="IMPORT"):
    """Make sure a person has the events their existing records imply. Safe to run any number of times."""
    a = c.execute("SELECT graduation_year FROM alumni WHERE id=?", (aid,)).fetchone()
    if not a:
        return
    if a["graduation_year"]:
        add_event(c, aid, "GRADUATION", "Graduated", event_date=str(a["graduation_year"]), source=source, by="system", dedupe=True)
    if not _has_type(c, aid, EMPLOYMENT_TYPES):
        o = c.execute("SELECT employer, position FROM offers WHERE alumni_id=? ORDER BY package_lpa DESC, id LIMIT 1", (aid,)).fetchone()
        if o and o["employer"]:
            add_event(c, aid, "FIRST_JOB", o["position"] or f"Joined {o['employer']}", organisation=o["employer"], source=source, by="system", dedupe=True)
    if not _has_type(c, aid, ("HIGHER_STUDIES",)):
        h = c.execute("SELECT degree, institution FROM higher_studies WHERE alumni_id=? ORDER BY id LIMIT 1", (aid,)).fetchone()
        if h and h["institution"]:
            add_event(c, aid, "HIGHER_STUDIES", h["degree"] or f"Studying at {h['institution']}", organisation=h["institution"], source=source, by="system", dedupe=True)
    if not _has_type(c, aid, ("ENTREPRENEURSHIP",)):
        v = c.execute("SELECT company FROM ventures WHERE alumni_id=? ORDER BY id LIMIT 1", (aid,)).fetchone()
        if v and v["company"]:
            add_event(c, aid, "ENTREPRENEURSHIP", f"Founder, {v['company']}", organisation=v["company"], source=source, by="system", dedupe=True)


def record_submission(c, aid, career_status, details, source="FORM"):
    """Turn a submitted form into timeline events, only where something actually changed. A change of employer is a
    JOB_CHANGE; the same employer with a different designation is a PROMOTION (the detail says exactly what changed, so
    a lateral move is not misreported as a rise)."""
    d = details or {}
    if career_status == "EMPLOYMENT":
        company, role = (d.get("company") or "").strip(), (d.get("designation") or "").strip()
        if not company:
            return
        last = c.execute("SELECT organisation, title FROM career_events WHERE alumni_id=? AND retracted_at IS NULL AND event_type IN "
                         "('FIRST_JOB','JOB_CHANGE','PROMOTION') ORDER BY id DESC LIMIT 1", (aid,)).fetchone()
        title = role or f"Joined {company}"
        if not last:
            add_event(c, aid, "FIRST_JOB", title, organisation=company, source=source, by="alumnus", dedupe=True)
        elif (last["organisation"] or "").strip().lower() != company.lower():
            add_event(c, aid, "JOB_CHANGE", title, organisation=company, detail=f"Moved from {last['organisation']}" if last["organisation"] else None,
                      source=source, by="alumnus", dedupe=True)
        elif role and (last["title"] or "").strip().lower() != role.lower():
            add_event(c, aid, "PROMOTION", role, organisation=company, detail=f"Designation changed from {last['title']} to {role}",
                      source=source, by="alumnus", dedupe=True)
    elif career_status == "HIGHER_STUDIES":
        uni, degree, spec = (d.get("university") or "").strip(), (d.get("degree") or "").strip(), (d.get("specialization") or "").strip()
        if uni and not c.execute("SELECT 1 FROM career_events WHERE alumni_id=? AND retracted_at IS NULL AND event_type='HIGHER_STUDIES' "
                                 "AND lower(COALESCE(organisation,''))=lower(?)", (aid, uni)).fetchone():
            add_event(c, aid, "HIGHER_STUDIES", " – ".join(x for x in (degree, spec) if x) or f"Studying at {uni}", organisation=uni,
                      detail=(f"Country: {d['country']}" if d.get("country") else None), source=source, by="alumnus")
    elif career_status == "ENTREPRENEURSHIP":
        name = (d.get("startup_name") or "").strip()
        if name:
            add_event(c, aid, "ENTREPRENEURSHIP", f"Founder, {name}", organisation=name,
                      detail=" · ".join(x for x in (d.get("business_domain"), d.get("stage")) if x) or None, source=source, by="alumnus", dedupe=True)
