import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config

_bearer = HTTPBearer(auto_error=False)


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


def make_jwt(email):
    return jwt.encode({"sub": email, "exp": int(time.time()) + config.JWT_HOURS * 3600}, config.SECRET_KEY, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials = Depends(_bearer)):
    if not cred:
        raise HTTPException(401, "Not authenticated")
    try:
        return jwt.decode(cred.credentials, config.SECRET_KEY, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired, please log in again")


def new_token():
    return secrets.token_urlsafe(24)
