"""User accounts, sessions, lockout and password reset. No FastAPI in here, so it is easy to unit test.

Functions that can *fail a security check* (`authenticate`, `consume_password_reset`) never raise for the expected
failure. They return a result so the caller can write the audit row and commit the failure counter first, then
answer with an error (raising inside `with db()` would roll both back).
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from . import config, rbac
from .security import burn_password_check, hash_password, make_session_jwt, ts, verify_password

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COMMON = {"password", "password1", "changeme", "changeme123", "admin123", "qwerty123", "letmein123", "welcome123"}
GENERIC_LOGIN_ERROR = "Incorrect email or password, or the account is temporarily locked"


class AccountError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


def normalize_email(e):
    return (e or "").strip().lower()


def validate_password(pw, email=None):
    """New passwords only (existing hashes are never re-checked against this)."""
    if not isinstance(pw, str) or len(pw) < config.MIN_PASSWORD_LENGTH:
        raise AccountError(f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters")
    if len(pw) > 128:
        raise AccountError("Password must be at most 128 characters")
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        raise AccountError("Password must contain at least one letter and one digit")
    low = pw.lower()
    if low in _COMMON or (email and low == normalize_email(email)):
        raise AccountError("That password is too easy to guess")


def public_user(r):
    d = {k: r[k] for k in ("id", "email", "full_name", "role", "is_active", "alumni_id", "last_login_at", "created_at")}
    d["is_active"] = bool(d["is_active"])
    d["locked"] = bool(r["locked_until"] and r["locked_until"] > ts())
    return d


def get_by_email(c, email):
    return c.execute("SELECT * FROM users WHERE email=?", (normalize_email(email),)).fetchone()


def _active_admins(c, excluding=None):
    q, a = "SELECT COUNT(*) n FROM users WHERE role='ADMIN' AND is_active=1", []
    if excluding is not None:
        q, a = q + " AND id<>?", [excluding]
    return c.execute(q, a).fetchone()["n"]


# ---------------------------------------------------------------- users
def create_user(c, *, email, password, role, full_name=None, alumni_id=None, skip_password_policy=False):
    email = normalize_email(email)
    if not EMAIL_RE.match(email) or len(email) > 200:
        raise AccountError("Enter a valid email address")
    if role not in rbac.ROLES:
        raise AccountError("role must be one of " + ", ".join(rbac.ROLES))
    if not skip_password_policy:
        validate_password(password, email)
    if role == rbac.ALUMNI:
        if not alumni_id:
            raise AccountError("An ALUMNI account must be linked to an alumni record (alumni_id)")
        if not c.execute("SELECT 1 FROM alumni WHERE id=?", (alumni_id,)).fetchone():
            raise AccountError("No alumni record with that id", 404)
        if c.execute("SELECT 1 FROM users WHERE alumni_id=?", (alumni_id,)).fetchone():
            raise AccountError("That alumni record already has an account", 409)
    elif alumni_id:
        raise AccountError("Only ALUMNI accounts are linked to an alumni record")
    if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise AccountError("A user with that email already exists", 409)
    now = ts()
    return c.execute("INSERT INTO users(email,password_hash,role,full_name,alumni_id,is_active,created_at,password_changed_at) "
                     "VALUES(?,?,?,?,?,1,?,?)",
                     (email, hash_password(password), role, (full_name or "").strip()[:120] or None, alumni_id, now, now)).lastrowid


def update_user(c, actor, uid, *, role=None, is_active=None, full_name=None):
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise AccountError("User not found", 404)
    new_role = role if role is not None else u["role"]
    new_active = bool(u["is_active"]) if is_active is None else bool(is_active)
    if role is not None and role not in rbac.ROLES:
        raise AccountError("role must be one of " + ", ".join(rbac.ROLES))
    if role is not None and role != u["role"]:
        if u["id"] == actor.user_id:
            raise AccountError("You cannot change your own role", 409)
        if role == rbac.ALUMNI and not u["alumni_id"]:
            raise AccountError("Link the account to an alumni record before making it an ALUMNI account", 409)
        if role != rbac.ALUMNI and u["alumni_id"]:
            raise AccountError("An account linked to an alumni record must stay an ALUMNI account", 409)
    if is_active is not None and not new_active and u["id"] == actor.user_id:
        raise AccountError("You cannot disable your own account", 409)
    if u["role"] == rbac.ADMIN and u["is_active"] and (new_role != rbac.ADMIN or not new_active) and _active_admins(c, uid) == 0:
        raise AccountError("There must always be at least one active administrator", 409)
    c.execute("UPDATE users SET role=?, is_active=?, full_name=COALESCE(?, full_name) WHERE id=?",
              (new_role, int(new_active), (full_name or "").strip()[:120] or None if full_name is not None else None, uid))
    if u["is_active"] and not new_active:
        revoke_user_sessions(c, uid)
    return {"before": {"role": u["role"], "is_active": bool(u["is_active"])}, "after": {"role": new_role, "is_active": new_active}}


def list_users(c):
    return [public_user(r) for r in c.execute("SELECT * FROM users ORDER BY role, email")]


# ---------------------------------------------------------------- login, lockout, sessions
def authenticate(c, email, password):
    """Returns (user_row_or_None, reason). reason: ok | unknown | bad_password | locked | inactive.
    Wrong passwords are counted; reaching LOCKOUT_THRESHOLD locks the account for LOCKOUT_MINUTES."""
    u = get_by_email(c, email)
    if not u:
        burn_password_check(password or "")
        return None, "unknown"
    now = ts()
    if u["locked_until"] and u["locked_until"] > now:
        burn_password_check(password or "")                     # a correct password during a lock still fails
        return None, "locked"
    if not verify_password(password or "", u["password_hash"]):
        n = u["failed_logins"] + 1
        if n >= config.LOCKOUT_THRESHOLD:
            c.execute("UPDATE users SET failed_logins=0, locked_until=? WHERE id=?",
                      (ts(datetime.now(timezone.utc) + timedelta(minutes=config.LOCKOUT_MINUTES)), u["id"]))
            return None, "locked"
        c.execute("UPDATE users SET failed_logins=? WHERE id=?", (n, u["id"]))
        return None, "bad_password"
    if not u["is_active"]:
        return None, "inactive"
    c.execute("UPDATE users SET failed_logins=0, locked_until=NULL, last_login_at=? WHERE id=?", (now, u["id"]))
    return u, "ok"


def start_session(c, user, ip=None, user_agent=None):
    sid = secrets.token_urlsafe(18)
    exp = datetime.now(timezone.utc) + timedelta(hours=config.JWT_HOURS)
    c.execute("INSERT INTO sessions(id,user_id,created_at,expires_at,last_seen_at,ip,user_agent) VALUES(?,?,?,?,?,?,?)",
              (sid, user["id"], ts(), ts(exp), ts(), ip, (user_agent or "")[:200]))
    return make_session_jwt(user["id"], user["email"], sid, exp), exp, sid


def list_sessions(c, user_id, current_sid=None):
    rows = c.execute("SELECT * FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY created_at DESC",
                     (user_id, ts())).fetchall()
    return [{"id": r["id"], "created_at": r["created_at"], "last_seen_at": r["last_seen_at"], "expires_at": r["expires_at"],
             "ip": r["ip"], "user_agent": r["user_agent"], "current": r["id"] == current_sid} for r in rows]


def revoke_session(c, user_id, sid):
    """Revoke one of this user's own sessions. Returns True if something was revoked."""
    return c.execute("UPDATE sessions SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
                     (ts(), sid, user_id)).rowcount > 0


def revoke_user_sessions(c, user_id, except_sid=None):
    q, a = "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", [ts(), user_id]
    if except_sid:
        q, a = q + " AND id<>?", a + [except_sid]
    return c.execute(q, a).rowcount


def purge_old_sessions(c, keep_days=30):
    c.execute("DELETE FROM sessions WHERE expires_at<?", (ts(datetime.now(timezone.utc) - timedelta(days=keep_days)),))
    c.execute("DELETE FROM password_resets WHERE expires_at<?", (ts(datetime.now(timezone.utc) - timedelta(days=keep_days)),))


# ---------------------------------------------------------------- passwords
def change_password(c, user_id, email, current, new, keep_sid=None):
    u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not u or not verify_password(current or "", u["password_hash"]):
        raise AccountError("Current password is incorrect", 403)
    validate_password(new, email)
    if verify_password(new, u["password_hash"]):
        raise AccountError("Choose a password you have not used just now")
    c.execute("UPDATE users SET password_hash=?, password_changed_at=?, failed_logins=0, locked_until=NULL WHERE id=?",
              (hash_password(new), ts(), user_id))
    return revoke_user_sessions(c, user_id, except_sid=keep_sid)      # every other device is signed out


def _hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def create_password_reset(c, email, ip=None, minutes=None):
    """Returns (user_row, raw_token), or None if the email is unknown / the account is disabled. The caller must answer
    identically either way so the endpoint cannot be used to discover which emails have accounts."""
    u = get_by_email(c, email)
    if not u or not u["is_active"]:
        return None
    c.execute("UPDATE password_resets SET used_at=? WHERE user_id=? AND used_at IS NULL", (ts(), u["id"]))   # older links die
    raw = secrets.token_urlsafe(32)
    c.execute("INSERT INTO password_resets(user_id,token_hash,created_at,expires_at,requested_ip) VALUES(?,?,?,?,?)",
              (u["id"], _hash_token(raw), ts(), ts(datetime.now(timezone.utc) + timedelta(minutes=minutes or config.RESET_TOKEN_MINUTES)), ip))
    return u, raw


def consume_password_reset(c, raw_token, new_password):
    """Returns (user_row_or_None, reason). reason: ok | invalid. A policy-violating password raises AccountError and
    leaves the token usable, so the person can try again."""
    r = c.execute("SELECT * FROM password_resets WHERE token_hash=?", (_hash_token(raw_token or ""),)).fetchone()
    if not r or r["used_at"] or r["expires_at"] <= ts():
        return None, "invalid"
    u = c.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
    if not u or not u["is_active"]:
        return None, "invalid"
    validate_password(new_password, u["email"])
    c.execute("UPDATE users SET password_hash=?, password_changed_at=?, failed_logins=0, locked_until=NULL WHERE id=?",
              (hash_password(new_password), ts(), u["id"]))
    c.execute("UPDATE password_resets SET used_at=? WHERE id=?", (ts(), r["id"]))
    revoke_user_sessions(c, u["id"])
    return u, "ok"
