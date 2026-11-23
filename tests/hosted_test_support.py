"""Configure a real Repo 1 test issuer and mint short-lived assertions."""

import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def make_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def configure_issuer(tmp_path, monkeypatch, signing_key):
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
