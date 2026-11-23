"""Repo 1 signs one short-lived assertion per user with its own private key."""

import os
from dataclasses import dataclass
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from services.hosted_entitlements import Plan


@dataclass(frozen=True)
class Principal:
    subject: str
    plan: Plan
    scopes: frozenset[str]


@dataclass(frozen=True)
class ServiceVerifier:
    public_key: RSAPublicKey
    issuer: str
    audience: str
    service_id: str
    plan_claim: str

    @classmethod
    def from_environment(cls) -> "ServiceVerifier":
        def required(name: str) -> str:
            value = os.environ.get(name, "").strip()
            if not value:
                raise RuntimeError(f"{name} is required for the hosted API")
            return value

        path = Path(required("VOICE_API_PUBLIC_KEY_FILE"))
        try:
            key = load_pem_public_key(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise RuntimeError("Cannot load VOICE_API_PUBLIC_KEY_FILE") from exc
        if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
            raise RuntimeError(
                "VOICE_API_PUBLIC_KEY_FILE requires a 2048-bit or larger RSA public key"
            )
        return cls(
            key,
            required("VOICE_API_ISSUER"),
            required("VOICE_API_AUDIENCE"),
            required("VOICE_API_SERVICE_ID"),
            os.environ.get("VOICE_API_PLAN_CLAIM", "plan"),
        )

    def verify(self, token: str) -> Principal:
        if len(token) > 8192:
            raise ValueError("Invalid service token")
        claims = jwt.decode(
            token,
            self.public_key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            options={
                "require": [
                    "iss",
                    "aud",
                    "sub",
                    "azp",
                    "scope",
                    "iat",
                    "exp",
                    self.plan_claim,
                ]
            },
        )
        issued, expires = claims["iat"], claims["exp"]
        if (
            type(issued) is not int
            or type(expires) is not int
            or not 0 < expires - issued <= 300
        ):
            raise ValueError("Invalid token lifetime")
        subject, scope = claims["sub"], claims["scope"]
        if (
            claims["azp"] != self.service_id
            or not isinstance(subject, str)
            or not subject.strip()
        ):
            raise ValueError("Invalid service identity")
        if not isinstance(scope, str):
            raise TypeError("Invalid service scope")
        return Principal(
            subject, Plan(claims[self.plan_claim]), frozenset(scope.split())
        )
