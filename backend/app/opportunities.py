"""Phase 4: a small opportunities board (jobs, internships, referrals).

Alumni (and admins) post; every signed-in member can read. The rules, all enforced here and in the routes:

  * Only the poster or an admin can edit or delete a post (`can_edit`).
  * Each post needs a title, company, category, description, a way to apply (an https link or an email address) and a
    closing date. After the closing date the post is "closed": hidden from the default list, shown (marked) on request.
  * The apply contact is whatever the poster chose to publish for this post. It is never taken from their profile.
  * A poster can have at most MAX_OPEN_PER_USER open posts at once (admins are exempt).

"Today" for closing dates is the calendar date in India (LOCAL_TZ), because closing dates are dates people type, not instants.
"""
import re
from datetime import date, datetime, timedelta, timezone

from . import profiles

CATEGORIES = {"JOB": "Job", "INTERNSHIP": "Internship", "REFERRAL": "Referral"}
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))        # IST
MAX_OPEN_PER_USER = 20
MAX_DAYS_AHEAD = 366
LIMITS = {"title": (3, 120), "company": (2, 120), "description": (10, 2000)}
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class OpportunityError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


def today():
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _text(field, value, multiline=False):
    v = _CTRL.sub("", (value or "").replace("\r\n", "\n")).strip()
    v = v if multiline else " ".join(v.split())
    lo, hi = LIMITS[field]
    if not lo <= len(v) <= hi:
        raise OpportunityError(f"{field.capitalize()} must be {lo}-{hi} characters")
    return v


def clean_contact(value):
    """An https link or an email address. -> (value, 'link' | 'email')."""
    v = (value or "").strip()
    if not v:
        raise OpportunityError("Say how to apply: an https link or an email address")
    if "@" in v and "://" not in v:
        if not _EMAIL.fullmatch(v) or len(v) > 120:
            raise OpportunityError("That email address does not look valid")
        return v.lower(), "email"
    try:
        return profiles.clean_url("portfolio_url", v), "link"
    except profiles.ProfileError:
        raise OpportunityError("Apply link must be a normal https:// address, or give an email address instead")


def clean(body, existing=None):
    """Validate a full post. `existing` (a row) relaxes the closing-date rule when the date is left unchanged,
    so an owner can fix a typo in a post that has already closed."""
    category = (body.get("category") or "").strip().upper()
    if category not in CATEGORIES:
        raise OpportunityError("Category must be one of " + ", ".join(CATEGORIES))
    contact, _ = clean_contact(body.get("apply_contact"))
    closing = (body.get("closing_date") or "").strip()
    try:
        d = date.fromisoformat(closing)
    except ValueError:
        raise OpportunityError("Closing date must be a date, for example 2026-12-31")
    if not (existing and existing["closing_date"] == closing):
        t = date.fromisoformat(today())
        if d < t:
            raise OpportunityError("Closing date cannot be in the past")
        if d > t + timedelta(days=MAX_DAYS_AHEAD):
            raise OpportunityError("Closing date must be within a year from today")
    return {"category": category, "title": _text("title", body.get("title")), "company": _text("company", body.get("company")),
            "description": _text("description", body.get("description"), multiline=True), "apply_contact": contact, "closing_date": closing}


def poster_name(principal, c):
    if principal.alumni_id:
        r = c.execute("SELECT name FROM alumni WHERE id=?", (principal.alumni_id,)).fetchone()
        if r:
            return r["name"]
    return (principal.full_name or "").strip() or ("Administrator" if principal.role == "ADMIN" else "Faculty")


def create(c, principal, body):
    data = clean(body)
    if not principal.has("opportunity.manage"):
        open_now = c.execute("SELECT COUNT(*) n FROM opportunities WHERE posted_by_user_id=? AND closing_date>=?",
                             (principal.user_id, today())).fetchone()["n"]
        if open_now >= MAX_OPEN_PER_USER:
            raise OpportunityError(f"You already have {MAX_OPEN_PER_USER} open posts. Delete or wait for some to close.", 429)
    now = _now()
    cur = c.execute(
        "INSERT INTO opportunities(category,title,company,description,apply_contact,closing_date,posted_by_user_id,posted_by_alumni_id,"
        "posted_by_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (data["category"], data["title"], data["company"], data["description"], data["apply_contact"], data["closing_date"],
         principal.user_id, principal.alumni_id, poster_name(principal, c), now, now))
    return cur.lastrowid, data


def _row(c, oid):
    r = c.execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone()
    if not r:
        raise OpportunityError("Opportunity not found", 404)
    return r


def can_edit(principal, row):
    if principal.has("opportunity.manage"):
        return True
    return principal.has("opportunity.post") and row["posted_by_user_id"] is not None and row["posted_by_user_id"] == principal.user_id


def update(c, principal, oid, body):
    row = _row(c, oid)
    if not can_edit(principal, row):
        raise OpportunityError("Only the person who posted this, or an admin, can change it", 403)
    data = clean(body, existing=row)
    c.execute("UPDATE opportunities SET category=?,title=?,company=?,description=?,apply_contact=?,closing_date=?,updated_at=? WHERE id=?",
              (data["category"], data["title"], data["company"], data["description"], data["apply_contact"], data["closing_date"], _now(), oid))
    return data, row


def delete(c, principal, oid):
    row = _row(c, oid)
    if not can_edit(principal, row):
        raise OpportunityError("Only the person who posted this, or an admin, can delete it", 403)
    c.execute("DELETE FROM opportunities WHERE id=?", (oid,))
    return row


def _item(r, principal, t):
    kind = "email" if "@" in r["apply_contact"] and "://" not in r["apply_contact"] else "link"
    return {"id": r["id"], "category": r["category"], "category_label": CATEGORIES[r["category"]], "title": r["title"],
            "company": r["company"], "description": r["description"], "apply_contact": r["apply_contact"], "apply_kind": kind,
            "closing_date": r["closing_date"], "is_closed": r["closing_date"] < t,
            "posted_by": {"name": r["posted_by_name"], "graduation_year": r["graduation_year"]},
            "created_at": r["created_at"], "updated_at": r["updated_at"],
            "mine": r["posted_by_user_id"] == principal.user_id, "can_edit": can_edit(principal, r)}


def listing(c, principal, category="", status="open", search="", mine=False, page=1, page_size=20):
    """The board. status: open (default) | closed | all. Raises OpportunityError for a value that is not allowed."""
    t = today()
    where, args = [], []
    category = (category or "").strip().upper()
    if category and category != "ALL":
        if category not in CATEGORIES:
            raise OpportunityError("category must be all|" + "|".join(CATEGORIES))
        where.append("o.category=?")
        args.append(category)
    if status not in ("open", "closed", "all"):
        raise OpportunityError("status must be open, closed or all")
    if status == "open":
        where.append("o.closing_date>=?")
        args.append(t)
    elif status == "closed":
        where.append("o.closing_date<?")
        args.append(t)
    if mine:
        where.append("o.posted_by_user_id=?")
        args.append(principal.user_id)
    term = (search or "").strip()
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(o.title LIKE ? ESCAPE '\\' OR o.company LIKE ? ESCAPE '\\' OR o.description LIKE ? ESCAPE '\\')")
        args += [like] * 3
    w = ("WHERE " + " AND ".join(where)) if where else ""
    base = f"FROM opportunities o LEFT JOIN alumni a ON a.id=o.posted_by_alumni_id {w}"
    total = c.execute(f"SELECT COUNT(*) n {base}", args).fetchone()["n"]
    # open posts first, the ones closing soonest at the top; then closed posts, the most recently closed first
    rows = c.execute(f"SELECT o.*, a.graduation_year graduation_year {base} "
                     "ORDER BY (o.closing_date<?) ASC, CASE WHEN o.closing_date>=? THEN o.closing_date END ASC, o.closing_date DESC, o.id DESC "
                     "LIMIT ? OFFSET ?", args + [t, t, page_size, (max(page, 1) - 1) * page_size]).fetchall()
    return {"items": [_item(r, principal, t) for r in rows], "total": total, "page": page, "page_size": page_size, "today": t}
