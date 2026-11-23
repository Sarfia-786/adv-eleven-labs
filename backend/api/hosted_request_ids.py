"""Correlate hosted HTTP responses with content-free diagnostic events."""

import logging
import re
from contextvars import ContextVar
from uuid import uuid4

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

current_request_id: ContextVar[str | None] = ContextVar(
    "hosted_request_id", default=None
)
logger = logging.getLogger("uvicorn.error.hosted_requests")
_IDENTIFIER = re.compile(rb"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _request_id(scope: Scope) -> str:
    supplied = [
        value for name, value in scope["headers"] if name.lower() == b"x-request-id"
    ]
    if len(supplied) == 1 and _IDENTIFIER.fullmatch(supplied[0]):
        return supplied[0].decode("ascii")
    return uuid4().hex


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        token = current_request_id.set(request_id)
        status = None

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            current_request_id.reset(token)
            logger.info(
                "hosted_request_completed request_id=%s status=%s",
                request_id,
                status,
                extra={"request_id": request_id, "status_code": status},
            )


class HostedFastAPI(FastAPI):
    def build_middleware_stack(self) -> ASGIApp:
        # Wrap the framework's error responses as well as user middleware.
        return RequestIdMiddleware(super().build_middleware_stack())
