"""Hosted listener. Start with uvicorn --app-dir backend hosted_api:create_app --factory."""

from collections.abc import Callable
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from services.hosted_entitlements import Capability, Plan, capabilities_for
from services.hosted_identity import Principal, ServiceVerifier


class Entitlements(BaseModel):
    api_version: Literal["v1"] = "v1"
    subject: str
    plan: Plan
    capabilities: list[Capability]


bearer = HTTPBearer(scheme_name="Repo1ServiceToken", auto_error=False)


def authenticated_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    unauthorized = HTTPException(
        401,
        detail={"code": "invalid_token"},
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )
    if credentials is None:
        raise unauthorized
    try:
        return request.app.state.service_verifier.verify(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
        raise unauthorized from None


def require_scope(scope: str) -> Callable[..., Principal]:
    def scoped(
        principal: Annotated[Principal, Depends(authenticated_principal)],
    ) -> Principal:
        if scope not in principal.scopes:
            raise HTTPException(
                403,
                detail={"code": "insufficient_scope"},
                headers={"Cache-Control": "no-store"},
            )
        return principal

    return scoped


router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticated_principal)])


@router.get("/entitlements")
def read_entitlements(
    response: Response,
    principal: Annotated[Principal, Depends(require_scope("entitlements:read"))],
) -> Entitlements:
    response.headers["Cache-Control"] = "no-store"
    return Entitlements(
        subject=principal.subject,
        plan=principal.plan,
        capabilities=sorted(capabilities_for(principal.plan)),
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hosted Voice API", version="1.0.0", docs_url=None, redoc_url=None
    )
    app.state.service_verifier = ServiceVerifier.from_environment()
    app.include_router(router)
    return app
