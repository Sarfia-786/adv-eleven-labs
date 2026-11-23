"""Issue #28: deterministic, fully offline Repo 1 status polling checks."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.repo1 import (  # noqa: E402
    CancelledJob,
    CompletedJob,
    FailedJob,
    HTTPResponse,
    JobAuthenticationError,
    JobHTTPError,
    JobPoller,
    JobPollingCancelled,
    JobPollingTimeout,
    JobProtocolError,
)
from examples.repo1.job_polling import _NoRedirect  # noqa: E402

ORIGIN = "https://voice.example.test"
URL = ORIGIN + "/api/v1/jobs/job-1"


class Clock:
    def __init__(self):
        self.current = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.current

    def sleep(self, seconds):
        assert 0 < seconds <= 0.25
        self.sleeps.append(seconds)
        self.current += seconds


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, token, timeout):
        self.calls.append((url, token, timeout))
        assert self.responses, "Unexpected extra poll"
        return self.responses.pop(0)


def reply(state=None, *, code=200, headers=None, **fields):
    data = {"job_id": "job-1", "status": state, **fields}
    return HTTPResponse(code, headers or {}, json.dumps(data).encode())


def setup(*responses, timeout=120, **kw):
    clock = Clock()
    transport = Transport(*responses)
    poller = JobPoller(
        service_origin=ORIGIN, token_provider=lambda: "secret-token", transport=transport,
        monotonic=clock.monotonic, sleep=clock.sleep, wall_clock=lambda: 1_700_000_000.0,
        initial_delay=0.5, max_delay=2.0, **kw,
    )
    return poller, transport, clock


def test_queued_running_completed_with_typed_artifact():
    poller, transport, clock = setup(
        reply("queued"), reply("running"), reply("completed", result={
            "artifacts": [{"id": "asset-1", "download_url": "/api/v1/audio/asset-1", "expires_at": "2026-11-23T00:00:00Z", "media_type": "audio/wav"}]
        }),
    )
    outcome = poller.poll(URL)
    assert isinstance(outcome, CompletedJob)
    assert outcome.job_id == "job-1"
    assert outcome.artifacts[0].id == "asset-1"
    assert outcome.artifacts[0].download_url == "/api/v1/audio/asset-1"
    assert outcome.artifacts[0].media_type == "audio/wav"
    assert clock.current == pytest.approx(101.5)
    assert len(transport.calls) == 3
    assert all(item[0] == URL and item[1] == "secret-token" for item in transport.calls)


@pytest.mark.parametrize("error", ["model not ready", {"message": "model not ready"}])
def test_failed_is_terminal_not_an_exception(error):
    poller, transport, _ = setup(reply("failed", error=error))
    result = poller.poll(URL)
    assert isinstance(result, FailedJob) and result.error == "model not ready"
    assert len(transport.calls) == 1


def test_remote_cancel_returns_typed_terminal_outcome():
    poller, transport, _ = setup(reply("cancelled"))
    assert isinstance(poller.poll(URL), CancelledJob)
    assert len(transport.calls) == 1


def test_rate_limit_honors_retry_after_and_safe_get():
    poller, transport, clock = setup(
        HTTPResponse(429, {"rEtRy-AfTeR": "3"}, b""), reply("completed"),
    )
    assert isinstance(poller.poll(URL), CompletedJob)
    assert clock.current == pytest.approx(103.0)
    assert len(transport.calls) == 2


def test_transient_503_then_success():
    poller, transport, clock = setup(HTTPResponse(503, {}, b"temporary"), reply("done"))
    assert isinstance(poller.poll(URL), CompletedJob)
    assert clock.current == pytest.approx(100.5)
    assert len(transport.calls) == 2


def test_retry_after_http_date():
    now = 1_700_000_000.0
    date = format_datetime(datetime.fromtimestamp(now + 4, tz=timezone.utc), usegmt=True)
    poller, _, clock = setup(HTTPResponse(503, {"Retry-After": date}, b""), reply("completed"))
    poller.poll(URL)
    assert clock.current == pytest.approx(104)


@pytest.mark.parametrize("status", [401, 403])
def test_expired_credentials_fail_fast(status):
    poller, transport, _ = setup(HTTPResponse(status, {}, b""), reply("completed"))
    with pytest.raises(JobAuthenticationError):
        poller.poll(URL)
    assert len(transport.calls) == 1


def test_token_provider_empty_is_rejected_without_a_request():
    transport = Transport(reply("completed"))
    poller = JobPoller(service_origin=ORIGIN, token_provider=lambda: "", transport=transport)
    with pytest.raises(JobAuthenticationError):
        poller.poll(URL)
    assert not transport.calls


def test_monotonic_deadline_not_exceeded_by_backoff():
    clock = Clock()
    calls = []

    def transport(url, token, timeout):
        calls.append(timeout)
        return reply("running")

    poller = JobPoller(service_origin=ORIGIN, token_provider=lambda: "x", transport=transport,
                       monotonic=clock.monotonic, sleep=clock.sleep, initial_delay=0.5)
    with pytest.raises(JobPollingTimeout):
        poller.poll(URL, timeout_seconds=1.2)
    assert clock.current == pytest.approx(101.2)
    assert calls == pytest.approx([1.2, 0.7])


def test_large_retry_after_expires_without_another_call():
    poller, transport, clock = setup(HTTPResponse(429, {"Retry-After": "300"}, b""))
    with pytest.raises(JobPollingTimeout):
        poller.poll(URL, timeout_seconds=1.0)
    assert len(transport.calls) == 1
    assert clock.current == pytest.approx(101)


def test_caller_cancellation_before_first_request():
    poller, transport, _ = setup(reply("completed"))
    with pytest.raises(JobPollingCancelled):
        poller.poll(URL, cancelled=lambda: True)
    assert not transport.calls


def test_caller_cancellation_during_sleep():
    clock = Clock()
    transport = Transport(reply("running"), reply("completed"))
    cancelled = False

    def sleep(seconds):
        nonlocal cancelled
        clock.sleep(seconds)
        cancelled = True

    poller = JobPoller(service_origin=ORIGIN, token_provider=lambda: "x", transport=transport,
                       monotonic=clock.monotonic, sleep=sleep)
    with pytest.raises(JobPollingCancelled):
        poller.poll(URL, cancelled=lambda: cancelled)
    assert len(transport.calls) == 1
    assert clock.current == pytest.approx(100.25)


@pytest.mark.parametrize("url", [
    "https://voice.example.test.evil.test/api/v1/jobs/1",
    "http://voice.example.test/api/v1/jobs/1",
    "https://voice.example.test:444/api/v1/jobs/1",
    "https://user@voice.example.test/api/v1/jobs/1",
    "https://voice.example.test/api/v1/jobs/1#fragment",
    "/api/v1/jobs/1",
])
def test_never_send_bearer_token_to_untrusted_origin(url):
    poller, transport, _ = setup(reply("completed"))
    with pytest.raises(ValueError):
        poller.poll(url)
    assert not transport.calls


def test_default_https_port_is_equivalent():
    poller, transport, _ = setup(reply("completed"))
    assert isinstance(poller.poll("https://voice.example.test:443/api/v1/jobs/1"), CompletedJob)
    assert transport.calls[0][0].endswith("/1")


def test_redirect_handler_never_forwards_authorization():
    handler = _NoRedirect()
    assert handler.redirect_request(None, None, 302, "Redirect", {}, "https://evil.test") is None


def test_malformed_json_and_unknown_state_are_protocol_errors():
    bad_json, _, _ = setup(HTTPResponse(200, {}, b"bad json"))
    with pytest.raises(JobProtocolError):
        bad_json.poll(URL)
    unknown, _, _ = setup(reply("teleported"))
    with pytest.raises(JobProtocolError):
        unknown.poll(URL)


def test_invalid_artifact_is_a_protocol_error():
    poller, _, _ = setup(reply("completed", result={"artifacts": ["not an object"]}))
    with pytest.raises(JobProtocolError):
        poller.poll(URL)


def test_http_404_not_retried():
    poller, transport, _ = setup(HTTPResponse(404, {}, b""), reply("completed"))
    with pytest.raises(JobHTTPError) as ex:
        poller.poll(URL)
    assert ex.value.status == 404
    assert len(transport.calls) == 1


def test_transport_gets_remaining_time_budget():
    poller, transport, _ = setup(reply("completed"), request_timeout=0.8)
    assert isinstance(poller.poll(URL, timeout_seconds=5), CompletedJob)
    assert transport.calls[0][2] == pytest.approx(0.8)


def test_token_is_refreshed_per_safe_read():
    values = iter(["fresh-1", "fresh-2"])
    transport = Transport(reply("queued"), reply("completed"))
    clock = Clock()
    poller = JobPoller(service_origin=ORIGIN, token_provider=lambda: next(values), transport=transport,
                       monotonic=clock.monotonic, sleep=clock.sleep)
    poller.poll(URL)
    assert [call[1] for call in transport.calls] == ["fresh-1", "fresh-2"]


def test_invalid_retry_after_falls_back_to_bounded_backoff():
    poller, transport, clock = setup(
        HTTPResponse(429, {"Retry-After": "not-a-date"}, b""),
        HTTPResponse(503, {}, b""),
        HTTPResponse(503, {}, b""),
        reply("completed"),
    )
    poller.poll(URL)
    assert len(transport.calls) == 4
    assert clock.current == pytest.approx(103.5)


def test_too_large_body_is_rejected():
    poller, _, _ = setup(HTTPResponse(200, {}, b"x" * (1_048_576 + 1)))
    with pytest.raises(JobProtocolError):
        poller.poll(URL)
