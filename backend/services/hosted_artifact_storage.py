"""Private byte stores. All keys are derived from a verified owner and a UUID."""

import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from core.audio_validation import resolve_regular_file


class ByteStore(Protocol):
    def put(self, key: str, path: Path, media_type: str) -> None: ...
    def open(self, key: str, size_bytes: int) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...


class LocalStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        path = resolve_regular_file(self.root, key)
        if path is None:
            raise OSError("Invalid artifact location")
        return path

    def put(self, key: str, path: Path, media_type: str) -> None:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_TRUNC
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0)
        )
        with (
            path.open("rb") as source,
            os.fdopen(os.open(self.path(key), flags, 0o600), "wb") as output,
        ):
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())

    def open(self, key: str, size_bytes: int) -> BinaryIO:
        stream = self.path(key).open("rb")
        if os.fstat(stream.fileno()).st_size != size_bytes:
            stream.close()
            raise OSError("Stored audio has a different size")
        return stream

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


class S3Store:
    def __init__(self, bucket: str, endpoint: str | None):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            config=Config(
                signature_version="s3v4",
                connect_timeout=3,
                read_timeout=20,
                retries={"total_max_attempts": 2},
            ),
        )

    @contextmanager
    def errors(self):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            yield
        except (BotoCoreError, ClientError) as exc:
            raise OSError("Private object storage unavailable") from exc

    def require_unversioned(self) -> None:
        if self.client.get_bucket_versioning(Bucket=self.bucket).get("Status"):
            raise OSError("Private artifacts require an unversioned bucket")

    def put(self, key: str, path: Path, media_type: str) -> None:
        with self.errors(), path.open("rb") as source:
            self.require_unversioned()
            self.client.put_object(
                Bucket=self.bucket,
                Key="artifacts/" + key,
                Body=source,
                ContentLength=path.stat().st_size,
                ContentType=media_type,
            )

    def open(self, key: str, size_bytes: int) -> BinaryIO:
        with self.errors():
            result = self.client.get_object(Bucket=self.bucket, Key="artifacts/" + key)
            if result["ContentLength"] != size_bytes:
                result["Body"].close()
                raise OSError("Stored audio has a different size")
            return result["Body"]

    def delete(self, key: str) -> None:
        with self.errors():
            self.require_unversioned()
            self.client.delete_object(Bucket=self.bucket, Key="artifacts/" + key)


@dataclass(frozen=True)
class ArtifactStorage:
    store: ByteStore
    max_bytes: int
    ttl_seconds: int

    @classmethod
    def configured(cls) -> "ArtifactStorage | None":
        backend = os.environ.get("VOICE_ARTIFACT_BACKEND")
        if not backend:
            return None
        limit = int(os.environ.get("VOICE_ARTIFACT_MAX_BYTES", str(32 * 1024**2)))
        ttl = int(os.environ.get("VOICE_ARTIFACT_TTL_SECONDS", "86400"))
        if not 1 <= limit <= 256 * 1024**2 or not 1 <= ttl <= 30 * 86400:
            raise ValueError("Invalid artifact size or retention limit")
        if backend == "local":
            root = Path(os.environ["VOICE_ARTIFACT_DIR"])
            if not root.is_absolute():
                raise ValueError("VOICE_ARTIFACT_DIR requires an absolute private path")
            store = LocalStore(root)
        elif backend == "s3":
            store = S3Store(
                os.environ["OBJECT_STORAGE_BUCKET"],
                os.environ.get("OBJECT_STORAGE_ENDPOINT"),
            )
        else:
            raise ValueError("VOICE_ARTIFACT_BACKEND must be local or s3")
        return cls(store, limit, ttl)
