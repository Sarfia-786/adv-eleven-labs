"""Versioned hosted pronunciation dictionary endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from services.hosted_dictionaries import DictionaryRepository
from services.hosted_entitlements import Capability, capabilities_for
from services.hosted_identity import Principal
from sqlalchemy.engine import RowMapping

from api.hosted_dependencies import require_scope

router = APIRouter(prefix="/pronunciation-dictionaries")
Name = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00]+$"
    ),
]
Text = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=200, pattern=r"^[^\s\x00]([^\x00]*[^\s\x00])?$"
    ),
]


class DictionaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    entries: Annotated[dict[Text, Text], Field(max_length=256)]


class DictionarySummary(BaseModel):
    id: UUID
    name: str


class Dictionary(DictionarySummary):
    api_version: Literal["v1"] = "v1"
    entries: dict[str, str]


class DictionaryPage(BaseModel):
    api_version: Literal["v1"] = "v1"
    items: list[DictionarySummary]


Reader = Annotated[Principal, Depends(require_scope("dictionaries:read"))]
Writer = Annotated[Principal, Depends(require_scope("dictionaries:write"))]


def store(request: Request, principal: Principal) -> DictionaryRepository:
    if request.app.state.database is None:
        raise HTTPException(503, detail={"code": "storage_unavailable"})
    return DictionaryRepository(request.app.state.database, principal)


def require_edit(principal: Principal) -> None:
    if Capability.EXPRESSIVE_CONTROLS not in capabilities_for(principal.plan):
        raise HTTPException(403, detail={"code": "capability_required"})


def dictionary(row: RowMapping | None) -> Dictionary:
    if row is None:
        raise HTTPException(404, detail={"code": "dictionary_not_found"})
    return Dictionary.model_validate(row)


@router.post("", status_code=201)
def create(data: DictionaryInput, request: Request, principal: Writer) -> Dictionary:
    require_edit(principal)
    return dictionary(store(request, principal).create(data.name, data.entries))


@router.get("")
def list_owned(
    request: Request,
    principal: Reader,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
) -> DictionaryPage:
    rows = store(request, principal).list(limit, offset)
    return DictionaryPage(items=[DictionarySummary.model_validate(row) for row in rows])


@router.get("/{dictionary_id}")
def get(dictionary_id: UUID, request: Request, principal: Reader) -> Dictionary:
    return dictionary(store(request, principal).get(dictionary_id))


@router.put("/{dictionary_id}")
def replace(
    dictionary_id: UUID, data: DictionaryInput, request: Request, principal: Writer
) -> Dictionary:
    require_edit(principal)
    return dictionary(
        store(request, principal).replace(dictionary_id, data.name, data.entries)
    )


@router.delete("/{dictionary_id}", status_code=204)
def remove(dictionary_id: UUID, request: Request, principal: Writer) -> Response:
    if not store(request, principal).delete(dictionary_id):
        raise HTTPException(404, detail={"code": "dictionary_not_found"})
    return Response(status_code=204)
