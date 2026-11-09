import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config, rbac
from .db import db

_bearer = HTTPBearer(auto_error=False)
SESSION_EXPIRED = "Session expired, please log in again"
LAST_SEEN_EVERY_SECONDS = 60


def ts(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- passwords
def hash_password(pw, salt=None):
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return salt.hex() + "$" + dk.hex()


def verify_password(pw, stored):
    try:
        salt, _ = stored.split("$")
        return hmac.compare_digest(hash_password(pw, bytes.fromhex(salt)), stored)
    except Exception:
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))


def burn_password_check(pw):
    """Do the same work as a real check, so an unknown email takes as long as a wrong password (no account enumeration)."""
    verify_password(pw, _DUMMY_HASH)


# ---------------------------------------------------------------- tokens
def new_token():
    return secrets.token_urlsafe(24)


def make_session_jwt(user_id, email, session_id, expires_at):
    """`expires_at` is a datetime. The JWT is only honoured while its server-side session row is live."""
    return jwt.encode({"sub": email, "uid": user_id, "sid": session_id, "exp": int(expires_at.timestamp())},
                      config.SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------- who is calling
@dataclass(frozen=True)
class Principal:
    user_id: int
    email: str
    role: str
    session_id: str
    full_name: Optional[str] = None
    alumni_id: Optional[int] = None

    @property
    def permissions(self):
        return rbac.permissions_for(self.role)

    def has(self, permission):
        return rbac.has(self.role, permission)

    @property
    def is_staff(self):
        return self.role in rbac.STAFF_ROLES


def _principal_from_jwt(raw):
    """Validate the JWT *and* its session. The role is read from the database on every request, so a role change
    or a disabled account takes effect immediately instead of when the token happens to expire."""
    try:
        payload = jwt.decode(raw, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, SESSION_EXPIRED)
    sid, uid = payload.get("sid"), payload.get("uid")
    if not sid or not uid:                                     # tokens issued before sessions existed
        raise HTTPException(401, SESSION_EXPIRED)
    now = ts()
    with db() as c:
        r = c.execute("SELECT s.last_seen_at, s.expires_at, s.revoked_at, u.id uid, u.email, u.role, u.full_name, u.alumni_id, u.is_active "
                      "FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.user_id=?", (sid, uid)).fetchone()
        if not r or r["revoked_at"] or r["expires_at"] <= now or not r["is_active"]:
            raise HTTPException(401, SESSION_EXPIRED)
        if not r["last_seen_at"] or r["last_seen_at"] < ts(datetime.now(timezone.utc) - timedelta(seconds=LAST_SEEN_EVERY_SECONDS)):
            c.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (now, sid))
    return Principal(user_id=r["uid"], email=r["email"], role=r["role"], session_id=sid,
                     full_name=r["full_name"], alumni_id=r["alumni_id"])


def current_principal(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> Principal:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    return _principal_from_jwt(cred.credentials)


def optional_principal(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> Optional[Principal]:
    """For routes that also serve anonymous visitors: a missing or bad login simply means 'anonymous'."""
    if not cred:
        return None
    try:
        return _principal_from_jwt(cred.credentials)
    except HTTPException:
        return None


def require(permission):
    """Dependency factory: `who: Principal = Depends(require("alumni.read"))`."""
    if permission not in rbac.PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")      # catches typos at import time, not in production

    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not p.has(permission):
            raise HTTPException(403, "You do not have permission to do that")
        return p
    return dep


def current_user(p: Principal = Depends(current_principal)):
    """Backward-compatible: the signed-in user's email. New code should use `require(...)`."""
    return p.email
