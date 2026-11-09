"""Sliding-window rate limiting.

In-process and thread-safe, which matches the documented single-API-process deployment. If the API is ever run as
several processes, replace `RateLimiter` with a Redis-backed class that has the same `hit()` signature; callers
do not change.

Limits are `(max_requests, window_seconds)` and are looked up at call time, so tests and operators can change them.
"""
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from . import config

LIMITS = {
    "login": (8, 600),             # per (client IP, email): slows password guessing against one account
    "login_ip": (40, 600),         # per client IP: slows guessing across many accounts
    "reset_request": (5, 900),     # per client IP
    "reset_confirm": (10, 900),    # per client IP
    "public_read": (120, 60),      # alumni form page loads, per client IP
    "public_write": (20, 60),      # alumni form submissions, per client IP
    "public_token": (30, 60),      # per personal link, whoever presents it
    "profile_public": (120, 60),   # unauthenticated profile views, per client IP
}


class RateLimiter:
    def __init__(self, max_keys=50_000):
        self._hits = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(self, bucket, key, limit, window):
        """Record one request. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        k = (bucket, key)
        with self._lock:
            q = self._hits.get(k)
            if q is None:
                if len(self._hits) >= self._max_keys:          # bound memory under a flood of distinct keys
                    self._evict(now)
                q = self._hits[k] = deque()
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(window - (now - q[0])) + 1)
            q.append(now)
            return True, 0

    def _evict(self, now):
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > 3600]:
            del self._hits[k]
        if len(self._hits) >= self._max_keys:                 # still full: drop the oldest quarter
            for k in sorted(self._hits, key=lambda k: self._hits[k][-1] if self._hits[k] else 0)[: self._max_keys // 4]:
                del self._hits[k]

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def reset():
    limiter.reset()


def client_ip(request: Request):
    """The caller's IP. X-Forwarded-For is only believed when TRUST_PROXY_HOPS says how many proxies are in front of
    us, and then the entry added by the proxy nearest the client is used, so a client cannot choose its own address
    by sending a forged header."""
    peer = request.client.host if request.client else "unknown"
    hops = config.TRUST_PROXY_HOPS
    if hops <= 0:
        return peer
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(parts) >= hops:
        return parts[-hops]
    return parts[0] if parts else peer


def check(bucket, key):
    """Raise 429 when `key` has used up `bucket`. No-op when rate limiting is switched off."""
    if not config.RATE_LIMIT_ENABLED:
        return
    limit, window = LIMITS[bucket]
    ok, retry = limiter.hit(bucket, str(key), limit, window)
    if not ok:
        raise HTTPException(429, f"Too many requests. Please try again in {retry} seconds.", headers={"Retry-After": str(retry)})


def by_ip(bucket):
    """FastAPI dependency: limit `bucket` per client IP."""
    def dep(request: Request):
        check(bucket, client_ip(request))
    return dep
