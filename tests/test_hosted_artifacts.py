"""Real signed requests and repeatable private audio storage operations."""

import io
import os
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hosted_api import create_app
from hosted_test_support import bearer, configure_issuer, make_key

BASE = "/api/v1/artifacts/"
ROOT = Path(__file__).resolve().parents[1]


def audio(frames=80):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((1, 2, 8000, frames, "NONE", "not compressed"))
        writer.writeframes(b"\x01\x00" * frames)
    return output.getvalue()


@pytest.fixture(scope="module")
def key():
    return make_key()


def auth(key, user="alice", scope="artifacts:read artifacts:write"):
    return {**bearer(key, sub=user, scope=scope), "Content-Type": "audio/wav"}


@pytest.fixture
def config(tmp_path, monkeypatch, key):
    configure_issuer(tmp_path, monkeypatch, key)
    monkeypatch.setenv("VOICE_API_DATABASE_URL", f"sqlite:///{tmp_path / 'hosted.db'}")
    monkeypatch.setenv("VOICE_ARTIFACT_BACKEND", "local")
    monkeypatch.setenv("VOICE_ARTIFACT_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("VOICE_ARTIFACT_MAX_BYTES", "512")
    monkeypatch.setenv("VOICE_ARTIFACT_TTL_SECONDS", "60")
    command.upgrade(Config(str(ROOT / "alembic-hosted.ini")), "head")


@pytest.fixture
def client(config):
    with TestClient(create_app()) as api:
        yield api


def round_trip(client, key):
    url = BASE + str(uuid4())
    payload = audio()
    alice, bob = auth(key), auth(key, "bob")
    sent = client.put(url, headers=alice, content=payload)
    assert sent.status_code == 201, sent.text
    again = client.put(url, headers=alice, content=payload)
    assert again.status_code == 200
    assert again.json() == sent.json()
    assert client.put(url, headers=alice, content=audio(40)).status_code == 409
    reference = sent.json()["download_path"]
    foreign = client.get(reference, headers=bob)
    assert foreign.status_code == 404
    assert (
        foreign.json()
        == client.get(
            BASE + str(uuid4()),
            params={"expires_at": sent.json()["expires_at"]},
            headers=bob,
        ).json()
    )
    assert client.delete(reference, headers=bob).status_code == 204
    reply = client.get(reference, headers=alice)
    assert reply.content == payload
    assert reply.headers["content-type"] == "audio/wav"
    assert int(reply.headers["content-length"]) == len(payload)
    assert reply.headers["cache-control"] == "no-store"
    assert reply.headers["x-content-type-options"] == "nosniff"
    assert url.split("/")[-1] + ".wav" in reply.headers["content-disposition"]
    for _ in range(2):
        assert client.delete(reference, headers=alice).status_code == 204
    assert client.get(reference, headers=alice).status_code == 404


def test_local_round_trip(client, key):
    round_trip(client, key)


def test_reject_bad_uploads_before_storage(client, key):
    url = BASE + str(uuid4())
    assert client.put(url, content=audio()).status_code == 401
    assert (
        client.put(
            url, headers=auth(key, scope="artifacts:read"), content=audio()
        ).status_code
        == 403
    )
    assert client.put(url, headers=auth(key), content=b"not audio").status_code == 415
    assert client.put(url, headers=auth(key), content=audio()[:-2]).status_code == 415
    headers = {**auth(key), "Content-Type": "application/octet-stream"}
    assert client.put(url, headers=headers, content=audio()).status_code == 415
    too_big = iter([audio(), b"x" * 513])
    assert client.put(url, headers=auth(key), content=too_big).status_code == 413
    assert (
        client.get(url, params={"expires_at": 1}, headers=auth(key)).status_code == 404
    )


def test_s3_round_trip(config, key, monkeypatch):
    server_module = pytest.importorskip(
        "moto.server", reason="Install moto[s3] and Flask for the HTTP emulator"
    )
    import boto3

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("VOICE_ARTIFACT_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "private-audio")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    server = server_module.ThreadedMotoServer(
        ip_address="127.0.0.1", port=0, verbose=False
    )
    server.start()
    try:
        host, port = server.get_host_and_port()
        endpoint = f"http://{host}:{port}"
        monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", endpoint)
        s3 = boto3.client("s3", endpoint_url=endpoint)
        s3.create_bucket(Bucket="private-audio")
        with TestClient(create_app()) as client:
            round_trip(client, key)
            assert s3.list_objects_v2(Bucket="private-audio")["KeyCount"] == 0
            s3.put_bucket_versioning(
                Bucket="private-audio", VersioningConfiguration={"Status": "Enabled"}
            )
            assert (
                client.put(
                    BASE + str(uuid4()), headers=auth(key), content=audio()
                ).status_code
                == 503
            )

    finally:
        server.stop()


def test_expiry_precedes_storage_access(client, key, monkeypatch):
    import sqlalchemy as sa
    from services import hosted_artifacts
    from services.hosted_artifacts import artifacts, cleanup

    url = BASE + str(uuid4())
    old = client.put(url, headers=auth(key), content=audio()).json()
    db, storage = client.app.state.database, client.app.state.artifact_storage
    monkeypatch.setattr(hosted_artifacts, "time", lambda: old["expires_at"])
    with monkeypatch.context() as patch:
        patch.setattr(
            storage.store,
            "open",
            lambda *_: pytest.fail("A denied read opened storage"),
        )
        for user in ("alice", "bob"):
            assert (
                client.get(old["download_path"], headers=auth(key, user)).status_code
                == 404
            )
    assert cleanup(db, storage) == 0
    assert list(storage.store.root.iterdir()) == []
    with db.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(artifacts)) == 0
    fresh = client.put(url, headers=auth(key), content=audio(40)).json()
    assert client.delete(old["download_path"], headers=auth(key)).status_code == 204
    assert client.get(old["download_path"], headers=auth(key)).status_code == 404
    assert client.get(fresh["download_path"], headers=auth(key)).content == audio(40)


def test_partial_write_and_delete_recovery(client, key, monkeypatch):
    from services.hosted_artifacts import cleanup

    url = BASE + str(uuid4())
    db, storage = client.app.state.database, client.app.state.artifact_storage
    store = storage.store
    original = store.put

    def partial(obj_key, path, mime):
        original(obj_key, path, mime)
        raise OSError("lost storage acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(store, "put", partial)
        assert client.put(url, headers=auth(key), content=audio()).status_code == 503
    assert list(store.root.iterdir()) == []
    assert (
        client.get(url, params={"expires_at": 1}, headers=auth(key)).status_code == 404
    )
    uploaded = client.put(url, headers=auth(key), content=audio())
    assert uploaded.status_code == 201
    reference = uploaded.json()["download_path"]

    def fail_delete(*_):
        raise OSError("temporarily unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(store, "delete", fail_delete)
        assert client.delete(reference, headers=auth(key)).status_code == 503
        assert client.get(reference, headers=auth(key)).status_code == 404
        assert cleanup(db, storage) == 1
    assert cleanup(db, storage) == 0
    assert list(store.root.iterdir()) == []
    assert client.put(url, headers=auth(key), content=audio()).status_code == 404


def test_same_id_concurrent_upload_and_tenant_namespace(client, key):
    from concurrent.futures import ThreadPoolExecutor

    url = BASE + str(uuid4())

    def put(_):
        return client.put(url, headers=auth(key), content=audio()).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(put, range(4))) == [200, 200, 200, 201]
    assert (
        client.put(url, headers=auth(key, "bob"), content=audio(40)).status_code == 201
    )
    for subject, data in [("bob", audio(40)), ("alice", audio())]:
        ref = client.put(url, headers=auth(key, subject), content=data).json()[
            "download_path"
        ]
        assert client.get(ref, headers=auth(key, subject)).content == data


def test_mp3_and_content_mismatch(tmp_path, monkeypatch, key, config):
    import numpy as np
    import soundfile as sf

    monkeypatch.setenv("VOICE_ARTIFACT_MAX_BYTES", "65536")
    path = tmp_path / "source.mp3"
    sf.write(path, np.zeros(16000, dtype="float32"), 16000, format="MP3")
    payload = path.read_bytes()
    url = BASE + str(uuid4())
    with TestClient(create_app()) as client:
        assert client.put(url, headers=auth(key), content=payload).status_code == 415
        headers = {**auth(key), "Content-Type": "audio/mpeg"}
        uploaded = client.put(url, headers=headers, content=payload)
        assert uploaded.status_code == 201
        reply = client.get(uploaded.json()["download_path"], headers=auth(key))
        assert reply.content == payload
        assert ".mp3" in reply.headers["content-disposition"]
        assert reply.headers["content-type"] == "audio/mpeg"


def test_disposable_postgres_round_trip(tmp_path, monkeypatch, key):
    import sqlalchemy as sa

    url = os.environ.get("VOICE_TEST_EMPTY_POSTGRES_URL")
    if not url:
        pytest.skip(
            "Set VOICE_TEST_EMPTY_POSTGRES_URL to a disposable empty PostgreSQL database"
        )
    check = sa.create_engine(url)
    try:
        assert (
            check.dialect.name == "postgresql"
            and not sa.inspect(check).get_table_names()
        )
    finally:
        check.dispose()
    configure_issuer(tmp_path, monkeypatch, key)
    monkeypatch.setenv("VOICE_ARTIFACT_BACKEND", "local")
    monkeypatch.setenv("VOICE_ARTIFACT_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("VOICE_API_DATABASE_URL", url)
    migration = Config(str(ROOT / "alembic-hosted.ini"))
    command.upgrade(migration, "head")
    command.upgrade(migration, "head")
    with TestClient(create_app()) as client:
        round_trip(client, key)
        route = "/api/v1/pronunciation-dictionaries"
        owner = bearer(
            key, scope="dictionaries:read dictionaries:write", plan="premium"
        )
        other = bearer(key, sub="other", scope="dictionaries:read")
        entry = client.post(
            route, headers=owner, json={"name": "Voice", "entries": {"SQL": "sequel"}}
        )
        assert entry.status_code == 201
        dictionary = route + "/" + entry.json()["id"]
        assert client.get(dictionary, headers=other).status_code == 404
        assert (
            client.put(
                dictionary, headers=owner, json={"name": "Updated", "entries": {}}
            ).status_code
            == 200
        )
        command.downgrade(migration, "h0001")
        assert client.get(dictionary, headers=owner).json()["name"] == "Updated"
        assert client.delete(dictionary, headers=owner).status_code == 204
