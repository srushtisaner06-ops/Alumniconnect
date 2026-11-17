"""Phase 3: basic alumni connections.

An alumnus sends a request to another alumnus whose profile they are allowed to see; the recipient accepts or rejects it.
That is all. No messaging, no recommendations, no blocking.

Rules (each one is enforced here, not in the browser):

  * Only alumni with a linked record take part (students and staff have no alumni_id).
  * You can only connect with someone whose profile you may see. Anyone else answers 404, exactly like a person who does
    not exist, so a PRIVATE profile is never revealed by trying to connect to it.
  * One live relationship per pair: a second request in either direction is refused while one is PENDING or ACCEPTED.
  * A rejected request cannot be re-sent for RETRY_AFTER_REJECTION_DAYS, and at most MAX_PENDING_SENT can wait at once.
  * Contact details (email, phone, WhatsApp) are NEVER part of a connection, accepted or not. A connection only shows the
    profile fields the person already shares under the visibility rules in visibility.py.

Statuses: PENDING -> ACCEPTED | REJECTED (by the recipient) | CANCELLED (withdrawn by the sender); an ACCEPTED connection
can later be removed by either person (CANCELLED). Rows are kept as history.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

from . import visibility

PENDING, ACCEPTED, REJECTED, CANCELLED = "PENDING", "ACCEPTED", "REJECTED", "CANCELLED"
MESSAGE_MAX = 300
MAX_PENDING_SENT = 20
RETRY_AFTER_REJECTION_DAYS = 30
_FMT = "%Y-%m-%d %H:%M:%S"


class ConnectionRefused(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


def _now():
    return datetime.now(timezone.utc)


def _ts(dt):
    return dt.strftime(_FMT)


def pair_key(a, b):
    lo, hi = sorted((int(a), int(b)))
    return f"{lo}:{hi}"


def clean_message(text):
    text = " ".join((text or "").split())
    if len(text) > MESSAGE_MAX:
        raise ConnectionRefused(f"The note can be at most {MESSAGE_MAX} characters")
    return text or None


def _person(c, alumni_id, viewer):
    """Who the other person is, as `viewer` may see them. Name and batch are always shown (the request itself is the
    reason you are looking at them); the rest of the profile only if their visibility setting allows this viewer."""
    row = c.execute("SELECT * FROM alumni WHERE id=?", (alumni_id,)).fetchone()
    if not row:
        return None
    out = {"id": row["id"], "name": row["name"], "graduation_year": row["graduation_year"], "profile_visible": False}
    if visibility.can_view(visibility.get_level(c, alumni_id), viewer, alumni_id):
        shared = visibility.member_view(c, row)
        shared.pop("timeline", None)
        out.update(shared)                       # career_status, organisations, profile (headline, links, skills...)
        out["profile_visible"] = True
    return out


def send(c, requester_id, recipient_id, message, viewer):
    """Create a request. Raises ConnectionRefused for every refusal; returns the new row's id."""
    if requester_id == recipient_id:
        raise ConnectionRefused("You cannot connect with yourself")
    target = c.execute("SELECT id FROM alumni WHERE id=?", (recipient_id,)).fetchone()
    if not target or not visibility.can_view(visibility.get_level(c, recipient_id), viewer, recipient_id):
        raise ConnectionRefused("Profile not found", 404)
    note = clean_message(message)
    live = c.execute("SELECT * FROM connections WHERE pair_key=? AND status IN ('PENDING','ACCEPTED')",
                     (pair_key(requester_id, recipient_id),)).fetchone()
    if live:
        if live["status"] == ACCEPTED:
            raise ConnectionRefused("You are already connected", 409)
        if live["requester_id"] == requester_id:
            raise ConnectionRefused("You have already sent this person a request", 409)
        raise ConnectionRefused("This person has already sent you a request. Accept it from your Connections page.", 409)
    last = c.execute("SELECT responded_at FROM connections WHERE requester_id=? AND recipient_id=? AND status='REJECTED' "
                     "ORDER BY id DESC LIMIT 1", (requester_id, recipient_id)).fetchone()
    if last and last["responded_at"]:
        retry = datetime.strptime(last["responded_at"], _FMT).replace(tzinfo=timezone.utc) + timedelta(days=RETRY_AFTER_REJECTION_DAYS)
        if retry > _now():
            raise ConnectionRefused(f"This request was declined. You can ask again after {retry.strftime('%d %b %Y')}.", 409)
    waiting = c.execute("SELECT COUNT(*) n FROM connections WHERE requester_id=? AND status='PENDING'", (requester_id,)).fetchone()["n"]
    if waiting >= MAX_PENDING_SENT:
        raise ConnectionRefused(f"You already have {MAX_PENDING_SENT} requests waiting for a reply. Withdraw one or wait for answers.", 429)
    try:
        cur = c.execute("INSERT INTO connections(requester_id,recipient_id,pair_key,status,message,created_at) VALUES(?,?,?,?,?,?)",
                        (requester_id, recipient_id, pair_key(requester_id, recipient_id), PENDING, note, _ts(_now())))
    except sqlite3.IntegrityError:               # two requests raced; the unique index let only one through
        raise ConnectionRefused("A request between you two is already open", 409)
    return cur.lastrowid


def _mine(c, cid, me):
    row = c.execute("SELECT * FROM connections WHERE id=? AND (requester_id=? OR recipient_id=?)", (cid, me, me)).fetchone()
    if not row:
        raise ConnectionRefused("Connection not found", 404)
    return row


def respond(c, cid, me, accept):
    """The recipient answers a PENDING request. -> the other person's alumni id."""
    row = _mine(c, cid, me)
    if row["recipient_id"] != me:
        raise ConnectionRefused("Only the person who received the request can answer it", 403)
    if row["status"] != PENDING:
        raise ConnectionRefused("This request has already been answered or withdrawn", 409)
    c.execute("UPDATE connections SET status=?, responded_at=? WHERE id=?", (ACCEPTED if accept else REJECTED, _ts(_now()), cid))
    return row["requester_id"]


def remove(c, cid, me):
    """Withdraw your own PENDING request, or end an ACCEPTED connection (either person). -> (other id, previous status)."""
    row = _mine(c, cid, me)
    other = row["recipient_id"] if row["requester_id"] == me else row["requester_id"]
    if row["status"] == PENDING and row["requester_id"] == me:
        pass
    elif row["status"] == ACCEPTED:
        pass
    elif row["status"] == PENDING:
        raise ConnectionRefused("Use Reject to turn down a request you received", 409)
    else:
        raise ConnectionRefused("Nothing to remove", 409)
    c.execute("UPDATE connections SET status=?, responded_at=? WHERE id=?", (CANCELLED, _ts(_now()), cid))
    return other, row["status"]


def overview(c, me, viewer):
    """Everything the Connections page and the Directory buttons need, in one call."""
    rows = c.execute("SELECT * FROM connections WHERE (requester_id=? OR recipient_id=?) ORDER BY id DESC", (me, me)).fetchall()
    received, sent, accepted = [], [], []
    for r in rows:
        mine_sent = r["requester_id"] == me
        other = r["recipient_id"] if mine_sent else r["requester_id"]
        item = {"id": r["id"], "status": r["status"], "message": r["message"], "created_at": r["created_at"],
                "responded_at": r["responded_at"], "direction": "sent" if mine_sent else "received"}
        if r["status"] == ACCEPTED:
            accepted.append((item, other))
        elif r["status"] == PENDING and not mine_sent:
            received.append((item, other))
        elif mine_sent and r["status"] in (PENDING, REJECTED):
            sent.append((item, other))
    people = {}

    def build(pairs):
        out = []
        for item, other in pairs:
            if other not in people:
                people[other] = _person(c, other, viewer)
            if people[other]:
                out.append({**item, "person": people[other]})
        return out
    accepted.sort(key=lambda p: p[0]["responded_at"] or "", reverse=True)
    result = {"received": build(received), "sent": build(sent), "connections": build(accepted)}
    result["counts"] = {k: len(v) for k, v in result.items()}
    return result
