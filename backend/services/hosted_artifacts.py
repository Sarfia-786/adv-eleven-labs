"""Tenant-scoped artifact lifecycle with durable reservations and deletion retries."""

import argparse
import hashlib
from pathlib import Path
from time import time
from uuid import UUID

import sqlalchemy as sa
from core.audio_validation import is_playable_wav
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from services.hosted_artifact_storage import ArtifactStorage
from services.hosted_identity import Principal

artifacts = sa.table(
    "hosted_artifacts",
    *(
        sa.column(n)
        for n in (
            "owner_key",
            "id",
            "state",
            "media_type",
            "size_bytes",
            "sha256",
            "expires_at",
        )
    ),
)
c = artifacts.c
TYPES = {"audio/wav": "wav", "audio/mpeg": "mp3"}


class ArtifactError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def validate_audio(path: Path, media_type: str) -> None:
    if media_type == "audio/wav" and is_playable_wav(path):
        return
    if media_type == "audio/mpeg":
        import soundfile as sf

        try:
            with sf.SoundFile(path) as audio:
                if (
                    audio.format == "MP3"
                    and 0 < audio.frames <= audio.samplerate * 4 * 3600
                ):
                    decoded = sum(
                        len(block)
                        for block in audio.blocks(blocksize=16384, dtype="int16")
                    )
                    if decoded == audio.frames:
                        return
        except (OSError, RuntimeError, ValueError):
            pass
    raise ArtifactError(415, "invalid_audio")


def _identity(owner: str, resource_id: str):
    return sa.and_(c.owner_key == owner, c.id == resource_id)


def _key(owner: str, resource_id: str, expires_at: int) -> str:
    return f"{owner}-{resource_id}-{expires_at}"


class ArtifactRepository:
    def __init__(self, engine: Engine, storage: ArtifactStorage, principal: Principal):
        self.engine = engine
        self.storage = storage
        self.owner = principal.owner_key

    def put(self, artifact_id: UUID, path: Path, media_type: str):
        size = path.stat().st_size
        if size > self.storage.max_bytes:
            raise ArtifactError(413, "artifact_too_large")
        validate_audio(path, media_type)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        rid = str(artifact_id)
        identity = _identity(self.owner, rid)
        now = int(time())
        insert = sqlite_insert if self.engine.dialect.name == "sqlite" else pg_insert
        with self.engine.begin() as conn:
            conn.execute(
                insert(artifacts)
                .values(
                    owner_key=self.owner,
                    id=rid,
                    state="pending",
                    media_type=media_type,
                    size_bytes=size,
                    sha256=digest,
                    expires_at=now + self.storage.ttl_seconds,
                )
                .on_conflict_do_nothing(index_elements=[c.owner_key, c.id])
            )
        # The no-op UPDATE locks this reservation on both SQLite and PostgreSQL.
        # The committed pending row makes bytes recoverable even if the process dies during PUT.
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    artifacts.update()
                    .where(identity)
                    .values(state=c.state)
                    .returning(*artifacts.c)
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or row["expires_at"] <= int(time())
                or row["state"] in {"deleting", "deleted"}
            ):
                raise ArtifactError(404, "artifact_not_found")
            if row["sha256"] != digest or row["media_type"] != media_type:
                raise ArtifactError(409, "artifact_id_conflict")
            created = row["state"] == "pending"
            if created:
                key = _key(self.owner, rid, row["expires_at"])
                try:
                    self.storage.store.put(key, path, media_type)
                except OSError:
                    self.storage.store.delete(key)
                    raise
                conn.execute(artifacts.update().where(identity).values(state="ready"))
        return {
            "id": rid,
            "size_bytes": size,
            "media_type": media_type,
            "expires_at": row["expires_at"],
        }, created

    def open(self, artifact_id: UUID, expires_at: int):
        rid = str(artifact_id)
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    sa.select(c.media_type, c.size_bytes).where(
                        _identity(self.owner, rid),
                        c.state == "ready",
                        c.expires_at == expires_at,
                        c.expires_at > int(time()),
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ArtifactError(404, "artifact_not_found")
        return self.storage.store.open(
            _key(self.owner, rid, expires_at), row["size_bytes"]
        ), row

    def delete(self, artifact_id: UUID, expires_at: int) -> None:
        rid = str(artifact_id)
        with self.engine.begin() as conn:
            affected = conn.execute(
                artifacts.update()
                .where(
                    _identity(self.owner, rid),
                    c.expires_at == expires_at,
                    c.state != "deleted",
                )
                .values(state="deleting")
            ).rowcount
        if affected:
            _erase(self.engine, self.storage, self.owner, rid)


def _erase(engine, storage, owner, rid) -> None:
    identity = _identity(owner, rid)
    now = int(time())
    with engine.begin() as conn:
        row = (
            conn.execute(
                artifacts.update()
                .where(identity, sa.or_(c.state == "deleting", c.expires_at <= now))
                .values(state=c.state)
                .returning(c.state, c.expires_at)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return
        storage.store.delete(_key(owner, rid, row["expires_at"]))
        if row["expires_at"] <= now:
            conn.execute(artifacts.delete().where(identity))
        else:
            conn.execute(artifacts.update().where(identity).values(state="deleted"))


def cleanup(engine: Engine, storage: ArtifactStorage, limit: int = 100) -> int:
    """Sweep one bounded batch. Failed removals remain durable for the next run."""
    if not 1 <= limit <= 1000:
        raise ValueError("cleanup limit must be between 1 and 1000")
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(c.owner_key, c.id)
            .where(sa.or_(c.state == "deleting", c.expires_at <= int(time())))
            .order_by(c.expires_at, c.owner_key, c.id)
            .limit(limit)
        ).all()
    failures = 0
    for owner, rid in rows:
        try:
            _erase(engine, storage, owner, rid)
        except OSError:
            failures += 1
    return failures


if __name__ == "__main__":
    from services.hosted_database import hosted_database_url, hosted_engine

    parser = argparse.ArgumentParser(
        description="Remove expired audio and retry pending deletions"
    )
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    url, storage = hosted_database_url(), ArtifactStorage.configured()
    if url is None or storage is None:
        parser.error("Configure the hosted database and artifact storage")
    database = hosted_engine(url)
    try:
        failed = cleanup(database, storage, args.limit)
        if failed:
            parser.exit(1, f"{failed} artifact deletion(s) require retry\n")
    finally:
        database.dispose()
