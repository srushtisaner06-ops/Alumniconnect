"""Phase 5: basic events and registration.

Admins create, edit and delete events. Every signed-in member sees upcoming events and can register for one (and cancel).
Only admins see who registered. No capacity limits, no attendance tracking, no reminders (per the plan).

Rules enforced here:
  * An event has a name, description, date, time (24 h, India time), venue and an optional registration link (https).
  * A new event cannot be dated in the past; an edit that leaves the date unchanged is always allowed.
  * You can register for, or cancel, an event only until it starts. One registration per person per event.
  * Deleting an event removes its registrations (the audit log records how many).

"Now" is India time (LOCAL_TZ), because event dates and times are typed by people at the college.
"""
import re
from datetime import date, datetime, timedelta, timezone

from . import profiles

LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))        # IST
MAX_DAYS_AHEAD = 731
LIMITS = {"name": (3, 150), "description": (10, 3000), "venue": (2, 200)}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class EventError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


def now_local():
    return datetime.now(LOCAL_TZ)


def _stamp(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")


def _text(field, value, multiline=False):
    v = _CTRL.sub("", (value or "").replace("\r\n", "\n")).strip()
    v = v if multiline else " ".join(v.split())
    lo, hi = LIMITS[field]
    if not lo <= len(v) <= hi:
        raise EventError(f"{field.capitalize()} must be {lo}-{hi} characters")
    return v


def _link(value):
    v = (value or "").strip()
    if not v:
        return None
    try:
        return profiles.clean_url("portfolio_url", v)       # the "any public https site" rule
    except profiles.ProfileError:
        raise EventError("Registration link must be a normal https:// address")


def clean(body, existing=None):
    try:
        d = date.fromisoformat((body.get("event_date") or "").strip())
    except ValueError:
        raise EventError("Date must look like 2026-12-31")
    t = (body.get("event_time") or "").strip()
    if not _TIME.match(t):
        raise EventError("Time must look like 18:30 (24-hour clock)")
    if not (existing and existing["event_date"] == d.isoformat()):
        today = now_local().date()
        if d < today:
            raise EventError("The date cannot be in the past")
        if d > today + timedelta(days=MAX_DAYS_AHEAD):
            raise EventError("The date must be within two years from today")
    return {"name": _text("name", body.get("name")), "description": _text("description", body.get("description"), True),
            "event_date": d.isoformat(), "event_time": t, "venue": _text("venue", body.get("venue")),
            "registration_link": _link(body.get("registration_link"))}


def has_started(event_date, event_time):
    return f"{event_date} {event_time}" <= now_local().strftime("%Y-%m-%d %H:%M")


def _event(c, eid):
    r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not r:
        raise EventError("Event not found", 404)
    return r


def create(c, principal, body):
    data = clean(body)
    now = _stamp()
    cur = c.execute("INSERT INTO events(name,description,event_date,event_time,venue,registration_link,created_by_user_id,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)", (data["name"], data["description"], data["event_date"], data["event_time"], data["venue"],
                                                  data["registration_link"], principal.user_id, now, now))
    return cur.lastrowid, data


def update(c, eid, body):
    row = _event(c, eid)
    data = clean(body, existing=row)
    c.execute("UPDATE events SET name=?,description=?,event_date=?,event_time=?,venue=?,registration_link=?,updated_at=? WHERE id=?",
              (data["name"], data["description"], data["event_date"], data["event_time"], data["venue"], data["registration_link"], _stamp(), eid))
    return data


def delete(c, eid):
    row = _event(c, eid)
    n = c.execute("SELECT COUNT(*) n FROM event_registrations WHERE event_id=?", (eid,)).fetchone()["n"]
    c.execute("DELETE FROM events WHERE id=?", (eid,))
    return row, n


def listing(c, principal, when="upcoming", search="", page=1, page_size=20):
    """when: upcoming (default) | past | all. Upcoming events come soonest first, past ones most recent first."""
    if when not in ("upcoming", "past", "all"):
        raise EventError("when must be upcoming, past or all")
    nowkey = now_local().strftime("%Y-%m-%d %H:%M")
    start = "(e.event_date || ' ' || e.event_time)"
    where, args = [], []
    if when == "upcoming":
        where.append(f"{start} > ?")
        args.append(nowkey)
    elif when == "past":
        where.append(f"{start} <= ?")
        args.append(nowkey)
    term = (search or "").strip()
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(e.name LIKE ? ESCAPE '\\' OR e.description LIKE ? ESCAPE '\\' OR e.venue LIKE ? ESCAPE '\\')")
        args += [like] * 3
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) n FROM events e {w}", args).fetchone()["n"]
    rows = c.execute(
        f"SELECT e.*, (SELECT COUNT(*) FROM event_registrations r WHERE r.event_id=e.id) registrations, "
        f"EXISTS(SELECT 1 FROM event_registrations r WHERE r.event_id=e.id AND r.user_id=?) mine FROM events e {w} "
        f"ORDER BY ({start} <= ?) ASC, CASE WHEN {start} > ? THEN {start} END ASC, {start} DESC, e.id DESC LIMIT ? OFFSET ?",
        [principal.user_id] + args + [nowkey, nowkey, page_size, (max(page, 1) - 1) * page_size]).fetchall()
    manage = principal.has("event.manage")
    items = []
    for r in rows:
        past = has_started(r["event_date"], r["event_time"])
        items.append({"id": r["id"], "name": r["name"], "description": r["description"], "event_date": r["event_date"],
                      "event_time": r["event_time"], "venue": r["venue"], "registration_link": r["registration_link"], "is_past": past,
                      "registered": bool(r["mine"]), "can_register": principal.has("event.register") and not past and not r["mine"],
                      "registration_count": r["registrations"] if manage else None, "can_manage": manage})
    return {"items": items, "total": total, "page": page, "page_size": page_size, "now": nowkey}


def register(c, principal, eid):
    row = _event(c, eid)
    if has_started(row["event_date"], row["event_time"]):
        raise EventError("This event has already started, so registration is closed", 409)
    if c.execute("SELECT 1 FROM event_registrations WHERE event_id=? AND user_id=?", (eid, principal.user_id)).fetchone():
        raise EventError("You are already registered for this event", 409)
    c.execute("INSERT INTO event_registrations(event_id,user_id,registered_at) VALUES(?,?,?)", (eid, principal.user_id, _stamp()))
    return row


def cancel(c, principal, eid):
    row = _event(c, eid)
    if has_started(row["event_date"], row["event_time"]):
        raise EventError("This event has already started, so it can no longer be changed", 409)
    cur = c.execute("DELETE FROM event_registrations WHERE event_id=? AND user_id=?", (eid, principal.user_id))
    if cur.rowcount == 0:
        raise EventError("You are not registered for this event", 404)
    return row


def participants(c, eid):
    """Who registered, for an admin. Name comes from the person's alumni record when they have one, else their account."""
    ev = _event(c, eid)
    rows = c.execute(
        "SELECT r.registered_at, u.email, u.role, COALESCE(a.name, NULLIF(u.full_name,''), u.email) name, a.graduation_year "
        "FROM event_registrations r JOIN users u ON u.id=r.user_id LEFT JOIN alumni a ON a.id=u.alumni_id "
        "WHERE r.event_id=? ORDER BY r.registered_at, r.id", (eid,)).fetchall()
    return {"event": {"id": ev["id"], "name": ev["name"], "event_date": ev["event_date"], "event_time": ev["event_time"]},
            "count": len(rows), "items": [dict(r) for r in rows]}
