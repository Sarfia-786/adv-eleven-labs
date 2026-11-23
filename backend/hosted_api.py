"""Hosted listener. Start with uvicorn --app-dir backend hosted_api:create_app --factory."""

from contextlib import asynccontextmanager
from typing import Annotated, Literal

from api.hosted_dependencies import authenticated_principal, require_scope
from api.hosted_dictionaries import router as dictionary_router
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from services.hosted_database import hosted_database_url, hosted_engine
from services.hosted_entitlements import Capability, Plan, capabilities_for
from services.hosted_identity import Principal, ServiceVerifier
from sqlalchemy.exc import DBAPIError


class Entitlements(BaseModel):
    api_version: Literal["v1"] = "v1"
    subject: str
    plan: Plan
    capabilities: list[Capability]


router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticated_principal)])


@router.get("/entitlements")
def read_entitlements(
    principal: Annotated[Principal, Depends(require_scope("entitlements:read"))],
) -> Entitlements:
    return Entitlements(
        subject=principal.subject,
        plan=principal.plan,
        capabilities=sorted(capabilities_for(principal.plan)),
    )


router.include_router(dictionary_router)


def create_app() -> FastAPI:
    database_url = hosted_database_url()
    database = hosted_engine(database_url) if database_url is not None else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            if database is not None:
                database.dispose()

    app = FastAPI(
        title="Hosted Voice API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.service_verifier = ServiceVerifier.from_environment()
    app.state.database = database

    @app.middleware("http")
    async def private_response(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DBAPIError)
    async def storage_unavailable(request: Request, exc: DBAPIError):
        return JSONResponse(
            {"detail": {"code": "storage_unavailable"}}, status_code=503
        )

    app.include_router(router)
    return app
