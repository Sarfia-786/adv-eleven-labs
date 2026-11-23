"""Verified identity and scope dependencies shared by hosted routers."""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from services.hosted_identity import Principal

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
