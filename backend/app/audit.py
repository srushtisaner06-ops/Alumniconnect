"""Audit trail.

`record()` writes in the caller's transaction, so an action and its audit row commit (or roll back) together.
Do NOT call it and then raise inside the same `with db()` block if you want the row kept: the rollback would discard
it. For failures, write the row, leave the block, then raise (see the login route).

The table is append-only (SQLite triggers in migration 1). Secrets are stripped from `detail` before storing.
"""
import json
from contextvars import ContextVar
from datetime import datetime, timezone

# Set once per request by middleware in main.py, so handlers do not have to pass the client address around.
client_ip_var = ContextVar("client_ip", default=None)

_SECRET_HINTS = ("password", "token", "secret", "authorization", "cookie", "jwt")
_MAX_DETAIL = 4000


def _clean(v, depth=0):
    if depth > 4:
        return "…"
    if isinstance(v, dict):
        return {str(k): ("[redacted]" if any(h in str(k).lower() for h in _SECRET_HINTS) else _clean(x, depth + 1))
                for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_clean(x, depth + 1) for x in list(v)[:50]]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return str(v)[:300]


def record(c, action, principal=None, *, ip=None, entity_type=None, entity_id=None, detail=None, outcome="OK", actor_email=None):
    ip = ip or client_ip_var.get()
    text = json.dumps(_clean(detail), ensure_ascii=False)[:_MAX_DETAIL] if detail else None
    c.execute(
        "INSERT INTO audit_logs(ts,actor_user_id,actor_email,actor_role,action,entity_type,entity_id,outcome,ip,detail) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
         principal.user_id if principal else None,
         principal.email if principal else actor_email,
         principal.role if principal else None,
         action, entity_type, None if entity_id is None else str(entity_id), outcome, ip, text))


def search(c, *, action=None, actor=None, entity_type=None, entity_id=None, outcome=None, since=None, until=None,
           page=1, page_size=50):
    where, args = [], []
    if action:
        where.append("action LIKE ?")
        args.append(action.replace("%", "") + "%")           # prefix match: "user" finds user.create, user.update
    if actor:
        where.append("actor_email LIKE ?")
        args.append(f"%{actor}%")
    if entity_type:
        where.append("entity_type=?")
        args.append(entity_type)
    if entity_id:
        where.append("entity_id=?")
        args.append(str(entity_id))
    if outcome:
        where.append("outcome=?")
        args.append(outcome)
    if since:
        where.append("ts>=?")
        args.append(since if len(since) > 10 else since + " 00:00:00")
    if until:
        where.append("ts<=?")
        args.append(until if len(until) > 10 else until + " 23:59:59")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) n FROM audit_logs {w}", args).fetchone()["n"]
    rows = c.execute(f"SELECT * FROM audit_logs {w} ORDER BY id DESC LIMIT ? OFFSET ?",
                     args + [page_size, (max(page, 1) - 1) * page_size]).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["detail"] = json.loads(d["detail"]) if d["detail"] else None
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}
