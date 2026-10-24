"""Streaming request-size limits and conservative security headers."""
from __future__ import annotations

from uuid import uuid4
from starlette.responses import JSONResponse


class _TooLarge(Exception):
    pass


class GuardMiddleware:
    def __init__(self, app, maximum=40 * 1024 * 1024):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size, started = 0, False
        request_id = uuid4().hex
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
        if declared > self.maximum:
            return await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)

        async def limited_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.maximum:
                    raise _TooLarge()
            return message

        async def protected_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                values = list(message.get("headers", []))
                values += [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                           (b"x-request-id", request_id.encode()),
                           (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'")]
                if scope["path"].startswith("/api/"):
                    values.append((b"cache-control", b"no-store"))
                message["headers"] = values
            await send(message)
        try:
            await self.app(scope, limited_receive, protected_send)
        except _TooLarge:
            if not started:
                await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, protected_send)
