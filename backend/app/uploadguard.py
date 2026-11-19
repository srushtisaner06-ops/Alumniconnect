"""Refuse an oversized upload from its Content-Length header, before the body is read.

Without this the server would accept (and spool to a temporary file) the whole body of a huge request before the route
could say no. Browsers always send Content-Length for a form upload, so a declared size over the limit is answered with
413 straight away. The route still enforces the limit on the bytes actually received, for clients that do not declare it.
"""
import json

from . import storage


class UploadSizeGuard:
    def __init__(self, app, paths, limit, overhead=1024 * 1024):
        self.app, self.paths, self.limit, self.overhead = app, set(paths), limit, overhead     # `limit` is a function, read per request

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] in self.paths:
            declared = dict(scope["headers"]).get(b"content-length", b"")
            limit = self.limit()
            if declared.isdigit() and int(declared) > limit + self.overhead:
                body = json.dumps({"detail": str(storage.too_large(limit))}).encode()
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
