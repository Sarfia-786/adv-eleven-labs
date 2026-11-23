import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from hosted_api import create_app


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def client(tmp_path, monkeypatch, signing_key):
    path = tmp_path / "repo1-public.pem"
    path.write_bytes(
        signing_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    for name, value in {
        "ISSUER": "issuer",
        "AUDIENCE": "voice",
        "SERVICE_ID": "repo1",
        "PUBLIC_KEY_FILE": str(path),
        "PLAN_CLAIM": "plan",
    }.items():
        monkeypatch.setenv("VOICE_API_" + name, value)
    return TestClient(create_app())


def bearer(key, **changes):
    now = int(time.time())
    claims = {
        "sub": "user-a",
        "iss": "issuer",
        "aud": "voice",
        "azp": "repo1",
        "scope": "entitlements:read",
        "plan": "free",
        "iat": now,
        "exp": now + 120,
    }
    claims.update(changes)
    return {"Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256")}


PATH = "/api/v1/entitlements"


@pytest.mark.parametrize("plan", ["free", "premium"])
def test_verified_plan(client, signing_key, plan):
    response = client.get(
        PATH,
        headers={
            **bearer(signing_key, plan=plan),
            "X-Plan": "premium",
            "X-User-Id": "different",
        },
        params={"user_id": "different"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["api_version"] == "v1"
    assert body["subject"] == "user-a"
    assert body["plan"] == plan
    assert ("instant_cloning" in body["capabilities"]) == (plan == "premium")


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "elsewhere"},
        {"aud": "other"},
        {"azp": "other"},
        {"sub": " "},
        {"plan": "admin"},
        {"exp": 1},
        {"iat": None},
        {"scope": ["entitlements:read"]},
    ],
)
def test_invalid_claims(client, signing_key, change):
    assert client.get(PATH, headers=bearer(signing_key, **change)).status_code == 401


@pytest.mark.parametrize(("claim", "offset"), [("exp", 601), ("iat", 60)])
def test_invalid_lifetime(client, signing_key, claim, offset):
    changes = {claim: int(time.time()) + offset}
    assert client.get(PATH, headers=bearer(signing_key, **changes)).status_code == 401


def test_configured_plan_claim(client, signing_key, monkeypatch):
    monkeypatch.setenv("VOICE_API_PLAN_CLAIM", "billing_tier")
    configured_client = TestClient(create_app())
    assert configured_client.get(PATH, headers=bearer(signing_key)).status_code == 401
    reply = configured_client.get(
        PATH, headers=bearer(signing_key, billing_tier="premium")
    )
    assert reply.status_code == 200
    assert reply.json()["plan"] == "premium"


def test_signature_scope_and_listener_boundary(client, signing_key):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert client.get(PATH, headers=bearer(other_key)).status_code == 401
    assert (
        client.get(PATH, headers=bearer(signing_key, scope="speech:read")).status_code
        == 403
    )
    assert (
        client.get(
            PATH, headers={"X-Forwarded-For": "127.0.0.1", "X-Plan": "premium"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/settings/hf-token/state", headers=bearer(signing_key)
        ).status_code
        == 404
    )
    assert client.get("/openapi.json").json()["paths"][PATH]["get"]["security"]


def test_unconfigured_gateway_refuses_startup(monkeypatch):
    monkeypatch.delenv("VOICE_API_PUBLIC_KEY_FILE", raising=False)
    with pytest.raises(RuntimeError, match="VOICE_API_PUBLIC_KEY_FILE"):
        create_app()
