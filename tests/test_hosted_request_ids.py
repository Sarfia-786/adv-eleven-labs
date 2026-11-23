"""Exercise correlation and access diagnostics over a real loopback listener."""

import asyncio
import logging
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn
from fastapi import Request
from hosted_api import create_app
from hosted_test_support import bearer, configure_issuer, make_key


@pytest.fixture(scope="module")
def signing_key():
    return make_key()


@pytest.fixture
def server(tmp_path, monkeypatch, signing_key):
    configure_issuer(tmp_path, monkeypatch, signing_key)
    app = create_app()
    arrived = 0
    gate = asyncio.Event()

    @app.get("/test-concurrent")
    async def concurrent(request: Request):
        from api.hosted_request_ids import current_request_id

        nonlocal arrived
        arrived += 1
        if arrived == 4:
            gate.set()
        await asyncio.wait_for(gate.wait(), timeout=5)
        return {"context": current_request_id.get(), "state": request.state.request_id}

    @app.post("/test-error")
    async def fail():
        raise RuntimeError("test failure")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(16)
        port = sock.getsockname()[1]
        config = uvicorn.Config(app, log_config=None, access_log=False, ws="none")
        listener = uvicorn.Server(config)
        thread = threading.Thread(
            target=listener.run, kwargs={"sockets": [sock]}, daemon=True
        )
        thread.start()
        try:
            end = time.monotonic() + 5
            while not listener.started:
                assert thread.is_alive() and time.monotonic() < end, (
                    "loopback startup failed"
                )
                time.sleep(0.01)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False
            ) as session:
                yield session
        finally:
            listener.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive(), "loopback listener did not shut down"


def test_response_and_event_have_the_same_id(server, signing_key, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.hosted_requests")
    route = "/api/v1/entitlements"
    token = bearer(signing_key)
    requests = [
        ("GET", route, token, None, 200),
        ("GET", route, {}, None, 401),
        ("GET", "/absent?private=query-secret", {}, None, 404),
        ("POST", "/test-error", token, b"private-body", 500),
    ]
    for method, path, headers, content, expected in requests:
        rid = f"repo1-{expected}"
        result = server.request(
            method, path, headers={**headers, "X-Request-ID": rid}, content=content
        )
        assert result.status_code == expected
        assert result.headers.get_list("x-request-id") == [rid]
    # A live client can receive the last body before the ASGI task finishes logging.
    deadline = time.monotonic() + 2
    while True:
        records = [
            r for r in caplog.records if r.name == "uvicorn.error.hosted_requests"
        ]
        if len(records) == len(requests) or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    assert [(r.request_id, r.status_code) for r in records] == [
        (f"repo1-{s}", s) for *_, s in requests
    ]
    assert all(r.request_id in r.getMessage() for r in records)
    events = " ".join(str(vars(record)) for record in records)
    for private in (token["Authorization"], "private-body", "query-secret"):
        assert private not in events


def test_invalid_missing_and_duplicate_ids_are_replaced(server):
    invalid = [
        [],
        [("X-Request-ID", "")],
        [("X-Request-ID", "x" * 65)],
        [("X-Request-ID", "abc,def")],
        [("X-Request-ID", "abc"), ("X-Request-ID", "def")],
    ]
    ids = [
        server.get("/absent", headers=headers).headers["x-request-id"]
        for headers in invalid
    ]
    assert len(set(ids)) == len(invalid)
    assert all(re.fullmatch(r"[0-9a-f]{32}", rid) for rid in ids)
    accepted = "a" * 64
    assert (
        server.get("/absent", headers={"X-Request-ID": accepted}).headers[
            "x-request-id"
        ]
        == accepted
    )


def test_concurrent_requests_keep_separate_contexts(server):
    def call(index):
        rid = f"parallel.{index}"
        result = server.get("/test-concurrent", headers={"X-Request-ID": rid})
        assert result.headers["x-request-id"] == rid
        assert result.json() == {"context": rid, "state": rid}

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(call, range(4)))


@pytest.mark.asyncio
async def test_request_context_is_restored_on_failure():
    from api.hosted_request_ids import RequestIdMiddleware, current_request_id

    async def failed(scope, receive, send):
        assert current_request_id.get() == "nested"
        raise ValueError("fixture")

    async def unused(*args):
        pytest.fail("unexpected I/O")

    token = current_request_id.set("outer")
    try:
        with pytest.raises(ValueError, match="fixture"):
            await RequestIdMiddleware(failed)(
                {"type": "http", "headers": [(b"x-request-id", b"nested")]},
                unused,
                unused,
            )
        assert current_request_id.get() == "outer"
    finally:
        current_request_id.reset(token)
