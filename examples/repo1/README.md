# Repo 1: hosted job polling (issue #28)

`job_polling.py` is a Python 3.11+ standard-library client for **polling an
already submitted job**. It does not submit, cancel, download artifacts, or
retry any write. The client checks that the complete status URL belongs to its
configured service origin **before** calling the token provider, and refuses
HTTP redirects to avoid leaking a bearer token. Production origins should use
HTTPS; `http://localhost` can be configured explicitly for local development.

```python
import os
import threading

from examples.repo1 import CompletedJob, FailedJob, CancelledJob, JobPoller, JobPollingCancelled

stop_polling = threading.Event()  # call stop_polling.set() from another thread
poller = JobPoller(
    service_origin="https://voice.example.test",
    token_provider=lambda: os.environ["VOICE_API_TOKEN"],  # supply fresh short-lived credentials
)

try:
    outcome = poller.poll(
        "https://voice.example.test/api/v1/jobs/<job-id>",  # example only; confirm #9 path
        timeout_seconds=120,
        cancelled=stop_polling.is_set,
    )
except JobPollingCancelled:
    print("Local polling stopped; the server job was NOT cancelled")
else:
    if isinstance(outcome, CompletedJob):
        print(outcome.artifacts)  # opaque refs; fetch privately with the hosted artifact API
    elif isinstance(outcome, FailedJob):
        print("Job failed:", outcome.error)
    elif isinstance(outcome, CancelledJob):
        print("Job was cancelled on the server")
```

The status **GET** accepts `queued`/`pending`/`running`, and terminal
`completed`/`done`/`succeeded`, `failed`, or `cancelled`/`canceled` in `status`
(or `state`). It expects `job_id` (or `id`) and optional `result.artifacts[]`,
`result.artifact`, or `result.audio_artifact` references containing `id` and/or
`download_url`/`url`. The original server payload is retained in each terminal
outcome. This is a **provisional adapter**: #9 must confirm final path, wire
status fields, error and artifact shape before a live integration is merged.

The poller uses a monotonic deadline (default 120s), bounded exponential
backoff (0.5–8s by default), and `Retry-After` in either seconds or HTTP-date
format on active/transient replies. A server-specified `Retry-After` may exceed
the backoff cap; the total sleep never exceeds the deadline. 429 and transient
5xx GETs are retried, other HTTP failures raise `JobHTTPError`, and 401/403
fail immediately as `JobAuthenticationError`. A cancelled local wait raises
`JobPollingCancelled`; it **does not** call a server cancellation endpoint.
Caller cancellation is checked between requests and every 0.25s of sleep;
request execution can block for up to the configured per-request timeout.

For deterministic tests, inject `transport(url, token, timeout) -> HTTPResponse`,
`monotonic`, `sleep`, and `wall_clock`; no server, tokens, audio engine, GPU, or
network access is required:

```sh
python -m pytest -q tests/test_repo1_job_polling.py
```

**Pending #9 live verification:** submit one hosted test job, pass the actual
URL from the submit response to `poll()`, verify terminal references can be
retrieved as the owning principal, and record API field/path and 429/503
semantics. Until then these tests prove only the offline client behavior.
