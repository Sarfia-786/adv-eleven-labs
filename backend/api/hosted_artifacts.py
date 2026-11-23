"""Authenticated streaming upload and download of private, time-limited audio."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal
from uuid import UUID

import anyio
from core.http_headers import content_disposition
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.hosted_artifacts import TYPES, ArtifactError, ArtifactRepository
from services.hosted_identity import Principal

from api.hosted_dependencies import require_scope

router = APIRouter(prefix="/artifacts")
Reader = Annotated[Principal, Depends(require_scope("artifacts:read"))]
Writer = Annotated[Principal, Depends(require_scope("artifacts:write"))]
Expiry = Annotated[int, Query(ge=1, le=9_223_372_036_854_775_807)]
BINARY = {kind: {"schema": {"type": "string", "format": "binary"}} for kind in TYPES}


class ArtifactInfo(BaseModel):
    api_version: Literal["v1"] = "v1"
    id: UUID
    size_bytes: int
    media_type: Literal["audio/wav", "audio/mpeg"]
    expires_at: int
    download_path: str


def repository(request: Request, principal: Principal) -> ArtifactRepository:
    database, storage = request.app.state.database, request.app.state.artifact_storage
    if database is None or storage is None:
        raise ArtifactError(503, "storage_unavailable")
    return ArtifactRepository(database, storage, principal)


@router.put(
    "/{artifact_id}",
    status_code=201,
    responses={200: {"model": ArtifactInfo}},
    openapi_extra={"requestBody": {"required": True, "content": BINARY}},
)
async def upload(
    artifact_id: UUID, request: Request, response: Response, principal: Writer
) -> ArtifactInfo:
    repo = repository(request, principal)
    media_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if media_type not in TYPES:
        raise ArtifactError(415, "invalid_audio")
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdecimal() or len(declared) > 20:
            raise HTTPException(400, detail={"code": "invalid_content_length"})
        if int(declared) > repo.storage.max_bytes:
            raise ArtifactError(413, "artifact_too_large")
    try:
        with TemporaryDirectory(prefix="voice-upload-") as directory:
            path = Path(directory) / ("upload." + TYPES[media_type])
            size = 0
            async with await anyio.open_file(path, "wb") as stream:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > repo.storage.max_bytes:
                        raise ArtifactError(413, "artifact_too_large")
                    await stream.write(chunk)
            if declared is not None and size != int(declared):
                raise HTTPException(400, detail={"code": "invalid_content_length"})
            data, created = await run_in_threadpool(
                repo.put, artifact_id, path, media_type
            )
    except OSError:
        raise ArtifactError(503, "storage_unavailable") from None
    response.status_code = 201 if created else 200
    return ArtifactInfo(
        **data, download_path=f"{request.url.path}?expires_at={data['expires_at']}"
    )


class AudioDownload(StreamingResponse):
    def __init__(self, stream, **kwargs):
        self.stream = stream
        super().__init__(iter(lambda: stream.read(64 * 1024), b""), **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.stream.close()


@router.get(
    "/{artifact_id}",
    response_class=StreamingResponse,
    responses={200: {"content": BINARY}},
)
def download(
    artifact_id: UUID, expires_at: Expiry, request: Request, principal: Reader
) -> StreamingResponse:
    try:
        stream, row = repository(request, principal).open(artifact_id, expires_at)
    except OSError:
        raise ArtifactError(503, "storage_unavailable") from None
    media_type = row["media_type"]
    name = f"{artifact_id}.{TYPES[media_type]}"
    return AudioDownload(
        stream,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(name),
            "Content-Length": str(row["size_bytes"]),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{artifact_id}", status_code=204)
def delete(
    artifact_id: UUID, expires_at: Expiry, request: Request, principal: Writer
) -> Response:
    try:
        repository(request, principal).delete(artifact_id, expires_at)
    except OSError:
        raise ArtifactError(503, "storage_unavailable") from None
    return Response(status_code=204)
