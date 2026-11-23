"""Dependency-free, read-only polling for the hosted Repo 1 job API.

The server-side hosted job contract is tracked in issue #9. Keep status parsing
isolated here so a finalized schema can be adopted without changing callers.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping, Protocol, TypeAlias
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_MAX_RESPONSE_BYTES = 1_048_576
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_ACTIVE_STATES = {"queued", "pending", "running"}
_COMPLETED_STATES = {"completed", "done", "succeeded"}
_FAILED_STATES = {"failed"}
_CANCELLED_STATES = {"cancelled", "canceled"}


class JobPollingError(Exception):
    """Base error for a client-side polling problem."""


class JobProtocolError(JobPollingError):
    """The job service returned an unsupported or malformed response."""


class JobAuthenticationError(JobPollingError):
    """The configured token was absent or rejected (401/403)."""


class JobHTTPError(JobPollingError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Job status GET returned HTTP {status}")


class JobPollingTimeout(JobPollingError, TimeoutError):
    """The monotonic deadline expired before a terminal result arrived."""


class JobPollingCancelled(JobPollingError):
    """The caller stopped local polling; no server-side cancel was sent."""


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def __call__(self, url: str, token: str, timeout: float) -> HTTPResponse: ...


@dataclass(frozen=True)
class ArtifactReference:
    """Opaque server-issued reference; download URLs are not fetched by polling."""

    id: str | None
    download_url: str | None
    expires_at: str | None = None
    media_type: str | None = None


@dataclass(frozen=True)
class CompletedJob:
    job_id: str
    artifacts: tuple[ArtifactReference, ...]
    payload: Mapping[str, Any]
    status: str = "completed"


@dataclass(frozen=True)
class FailedJob:
    job_id: str
    error: str | None
    payload: Mapping[str, Any]
    status: str = "failed"


@dataclass(frozen=True)
class CancelledJob:
    job_id: str
    payload: Mapping[str, Any]
    status: str = "cancelled"


JobOutcome: TypeAlias = CompletedJob | FailedJob | CancelledJob


class _NoRedirect(HTTPRedirectHandler):
    """Never forward a bearer credential to a redirected host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def urllib_get(url: str, token: str, timeout: float) -> HTTPResponse:
    """Default stdlib GET transport; HTTP errors become inspectable responses."""

    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, method="GET")
    opener = build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise JobProtocolError("Job status response exceeds the size limit")
        return HTTPResponse(response.status, dict(response.headers.items()), body)


def _origin_parts(url: str, *, origin: bool) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid service URL") from exc
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Service URLs must have an HTTP(S) origin without userinfo")
    if parsed.fragment or (origin and (parsed.path not in ("", "/") or parsed.query)):
        raise ValueError("Origin cannot contain a path/query/fragment and job URLs cannot contain fragments")
    if not origin and (not parsed.path or parsed.path == "/"):
        raise ValueError("A job URL must contain a job path")
    return parsed.scheme, parsed.hostname.lower(), port or (443 if parsed.scheme == "https" else 80)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next((str(value) for key, value in headers.items() if key.lower() == name.lower()), None)


def _retry_after(headers: Mapping[str, str], now: Callable[[], float]) -> float | None:
    raw = _header(headers, "Retry-After")
    if raw is None:
        return None
    raw = raw.strip()
    if raw.isascii() and raw.isdecimal():
        return float(raw) if len(raw) < 16 else math.inf
    try:
        date = parsedate_to_datetime(raw)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0.0, date.timestamp() - now())
    except (TypeError, ValueError, OverflowError, IndexError):
        return None


def _job_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("job_id", payload.get("id"))
    if not isinstance(value, str) or not value.strip():
        raise JobProtocolError("Job response must contain a nonempty job_id or id")
    return value


def _artifacts(payload: Mapping[str, Any]) -> tuple[ArtifactReference, ...]:
    result = payload.get("result")
    if result is not None and not isinstance(result, dict):
        raise JobProtocolError("Job result must be an object")
    data = result or payload
    references = data.get("artifacts")
    if references is None:
        single = data.get("artifact") or data.get("audio_artifact")
        references = [] if single is None else [single]
    if not isinstance(references, list):
        raise JobProtocolError("Job artifacts must be an array")
    output: list[ArtifactReference] = []
    for item in references:
        if not isinstance(item, dict):
            raise JobProtocolError("Each artifact reference must be an object")
        identifier = item.get("id", item.get("artifact_id"))
        url = item.get("download_url", item.get("url"))
        expiry = item.get("expires_at")
        media_type = item.get("media_type")
        if (identifier is None and url is None) or any(
            field is not None and (not isinstance(field, str) or not field)
            for field in (identifier, url, expiry, media_type)
        ):
            raise JobProtocolError("Artifact reference fields must be nonempty strings")
        output.append(ArtifactReference(identifier, url, expiry, media_type))
    return tuple(output)


def _terminal(payload: Mapping[str, Any]) -> JobOutcome | None:
    state = payload.get("status", payload.get("state"))
    if not isinstance(state, str):
        raise JobProtocolError("Job status must be a string")
    state = state.lower()
    if state in _ACTIVE_STATES:
        return None
    job_id = _job_id(payload)
    if state in _COMPLETED_STATES:
        return CompletedJob(job_id, _artifacts(payload), payload)
    if state in _FAILED_STATES:
        error = payload.get("error")
        if isinstance(error, dict):
            error = error.get("message")
        if error is not None and not isinstance(error, str):
            raise JobProtocolError("Job error must be a string or an object with a message")
        return FailedJob(job_id, error, payload)
    if state in _CANCELLED_STATES:
        return CancelledJob(job_id, payload)
    raise JobProtocolError(f"Unknown job status: {state!r}")


class JobPoller:
    """Poll one job's status by GET without retrying submission or cancelling it.

    Transport and time functions are injectable; cancelled is a cooperative
    callback, e.g. threading.Event().is_set. The sleep loop checks it at most
    every 0.25 s (outside of a potentially blocking HTTP GET).
    """

    def __init__(
        self,
        *,
        service_origin: str,
        token_provider: Callable[[], str],
        transport: Transport = urllib_get,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], float] = time.time,
        initial_delay: float = 0.5,
        max_delay: float = 8.0,
        request_timeout: float = 10.0,
    ) -> None:
        self._origin = _origin_parts(service_origin, origin=True)
        if any(not math.isfinite(v) or v <= 0 for v in (initial_delay, max_delay, request_timeout)) or initial_delay > max_delay:
            raise ValueError("Polling intervals/timeouts must be finite and positive, with initial_delay <= max_delay")
        self._token_provider = token_provider
        self._transport = transport
        self._monotonic = monotonic
        self._sleep = sleep
        self._wall_clock = wall_clock
        self._initial_delay = initial_delay
        self._max_delay = max_delay
        self._request_timeout = request_timeout

    def poll(
        self,
        job_url: str,
        *,
        timeout_seconds: float = 120.0,
        cancelled: Callable[[], bool] | None = None,
    ) -> JobOutcome:
        if _origin_parts(job_url, origin=False) != self._origin:
            raise ValueError("Job URL must be on the configured service origin")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        is_cancelled = cancelled or (lambda: False)
        deadline = self._monotonic() + timeout_seconds
        delay = self._initial_delay
        while True:
            if is_cancelled():
                raise JobPollingCancelled("Caller cancelled local polling")
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise JobPollingTimeout("Job polling deadline expired")
            token = self._token_provider()
            if not isinstance(token, str) or not token.strip():
                raise JobAuthenticationError("Token provider returned no usable token")
            response = self._transport(job_url, token, min(remaining, self._request_timeout))
            if is_cancelled():
                raise JobPollingCancelled("Caller cancelled local polling")
            if deadline - self._monotonic() <= 0:
                raise JobPollingTimeout("Job polling deadline expired")
            if response.status in (401, 403):
                raise JobAuthenticationError(f"Job status authorization failed (HTTP {response.status})")
            if response.status in (200, 202):
                if len(response.body) > _MAX_RESPONSE_BYTES:
                    raise JobProtocolError("Job status response exceeds the size limit")
                try:
                    payload = json.loads(response.body)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise JobProtocolError("Job status response is not valid JSON") from exc
                if not isinstance(payload, dict):
                    raise JobProtocolError("Job status response must be a JSON object")
                result = _terminal(payload)
                if result is not None:
                    return result
            elif response.status not in _RETRYABLE_HTTP:
                raise JobHTTPError(response.status)
            # Retry-After is a minimum server delay, not capped by client backoff.
            # The monotonic deadline still strictly bounds total waiting.
            retry_after = _retry_after(response.headers, self._wall_clock)
            pause = max(delay, retry_after or 0.0)
            delay = min(delay * 2, self._max_delay)
            wake = min(deadline, self._monotonic() + pause)
            while True:
                if is_cancelled():
                    raise JobPollingCancelled("Caller cancelled local polling")
                remaining_sleep = wake - self._monotonic()
                if remaining_sleep <= 0:
                    break
                self._sleep(min(remaining_sleep, 0.25))
