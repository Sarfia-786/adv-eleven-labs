"""Exercise issuer/subject ownership through the hosted HTTP and migration entry points."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hosted_api import create_app
from hosted_test_support import bearer, configure_issuer, make_key

ROOT = Path(__file__).resolve().parents[1]
PATH = "/api/v1/pronunciation-dictionaries"
BODY = {"name": "Studio", "entries": {"SQL": "sequel"}}
SCOPES = "dictionaries:read dictionaries:write"


def migrate():
    command.upgrade(Config(str(ROOT / "alembic-hosted.ini")), "head")


@pytest.fixture(scope="module")
def key():
    return make_key()


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "hosted.db"
    monkeypatch.setenv("VOICE_API_DATABASE_URL", f"sqlite:///{path}")
    return path


@pytest.fixture
def client(database, tmp_path, monkeypatch, key):
    configure_issuer(tmp_path, monkeypatch, key)
    migrate()
    with TestClient(create_app()) as api:
        yield api


def token(key, subject, **claims):
    return bearer(key, **{"scope": SCOPES, "plan": "premium", "sub": subject, **claims})


def test_two_tenants_own_their_dictionaries(client, key):
    alice, bob = token(key, "alice"), token(key, "bob")
    created = client.post(PATH, json=BODY, headers=alice)
    assert created.status_code == 201
    first = created.json()["id"]
    other = client.post(PATH, json=BODY, headers=bob)
    assert other.status_code == 201
    second = other.json()["id"]
    assert first != second
    for headers, expected in [(alice, first), (bob, second)]:
        response = client.get(PATH, headers=headers)
        assert [item["id"] for item in response.json()["items"]] == [expected]
        assert response.headers["cache-control"] == "no-store"

    for method in ("get", "put", "delete"):
        kwargs = {"json": BODY} if method == "put" else {}
        requester = getattr(client, method)
        foreign = requester(f"{PATH}/{first}", headers=bob, **kwargs)
        unknown = requester(f"{PATH}/{uuid4()}", headers=bob, **kwargs)
        assert foreign.status_code == unknown.status_code == 404
        assert foreign.json() == unknown.json()

    assert (
        client.get(f"{PATH}/{first}", headers=alice).json()["entries"]
        == BODY["entries"]
    )
    updated = client.put(
        f"{PATH}/{first}", headers=alice, json={"name": "Revised", "entries": {}}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Revised"
    assert client.delete(f"{PATH}/{first}", headers=alice).status_code == 204
    assert client.get(f"{PATH}/{second}", headers=bob).status_code == 200


def test_owner_is_bound_to_verified_issuer(client, monkeypatch, key):
    own = client.post(PATH, json=BODY, headers=token(key, "alice")).json()["id"]
    monkeypatch.setenv("VOICE_API_ISSUER", "second-issuer")
    with TestClient(create_app()) as second:
        caller = token(key, "alice", iss="second-issuer")
        assert second.get(f"{PATH}/{own}", headers=caller).status_code == 404
        assert second.get(PATH, headers=caller).json()["items"] == []


def test_scopes_entitlements_and_input(client, key):
    assert client.get(PATH).status_code == 401
    assert (
        client.get(
            PATH, headers=token(key, "u", scope="dictionaries:write")
        ).status_code
        == 403
    )
    assert (
        client.post(
            PATH, json=BODY, headers=token(key, "u", scope="dictionaries:read")
        ).status_code
        == 403
    )
    denied = client.post(
        PATH, json=BODY, headers={**token(key, "u", plan="free"), "X-Plan": "premium"}
    )
    assert denied.status_code == 403
    for bad in [
        {**BODY, "user_id": "someone"},
        {**BODY, "name": " "},
        {**BODY, "entries": {"": "abc"}},
    ]:
        assert client.post(PATH, headers=token(key, "u"), json=bad).status_code == 422
    assert (
        client.get(PATH, params={"limit": 0}, headers=token(key, "u")).status_code
        == 422
    )


def test_populated_database_survives_repeated_upgrade_and_hosted_downgrade(
    database, monkeypatch
):
    from api.routers.gallery import _init_gallery_db
    from core import db

    monkeypatch.setattr(db, "DB_PATH", str(database))
    db.init_db()
    _init_gallery_db()
    with db.db_conn() as conn:
        conn.execute("INSERT INTO voice_profiles(id, name) VALUES ('p', 'Original')")
        conn.execute(
            "INSERT INTO generation_history(id, profile_id, text) VALUES ('h', 'p', 'Saved')"
        )
        conn.execute("""INSERT INTO voice_gallery
            (id,name,character,category,source_type,audio_path,duration,created_at)
            VALUES ('g','Gallery','c','local','upload','saved.wav',2.0,0.0)""")

    def local_rows():
        with db.db_conn() as conn:
            return [
                tuple(conn.execute(f"SELECT * FROM {table}").fetchone())
                for table in (
                    "voice_profiles",
                    "voice_gallery",
                    "generation_history",
                    "alembic_version",
                )
            ]

    before = local_rows()
    migrate()
    migrate()
    assert local_rows() == before
    command.downgrade(Config(str(ROOT / "alembic-hosted.ini")), "base")
    assert local_rows() == before
    with sqlite3.connect(database) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='hosted_dictionaries'"
        ).fetchall()


def test_restart_pagination_and_downgrade_rights(client, key):
    owner = token(key, "u")
    ids = {client.post(PATH, headers=owner, json=BODY).json()["id"] for _ in range(3)}
    migrate()
    with TestClient(create_app()) as reopened:
        free = token(key, "u", plan="free")
        paged = [
            reopened.get(PATH, params={"limit": 1, "offset": i}, headers=free).json()[
                "items"
            ][0]["id"]
            for i in range(3)
        ]
        assert paged == sorted(ids)
        target = f"{PATH}/{paged[0]}"
        assert reopened.get(target, headers=free).json()["entries"] == BODY["entries"]
        assert reopened.put(target, headers=free, json=BODY).status_code == 403
        assert reopened.delete(target, headers=free).status_code == 204
        assert reopened.get(target, headers=free).status_code == 404


@pytest.mark.parametrize("configured", [False, True])
def test_storage_unavailable_preserves_entitlement_lookup(
    database, tmp_path, monkeypatch, key, configured
):
    configure_issuer(tmp_path, monkeypatch, key)
    if not configured:
        monkeypatch.delenv("VOICE_API_DATABASE_URL")
    with TestClient(create_app()) as api:
        assert api.get("/api/v1/entitlements", headers=bearer(key)).status_code == 200
        response = api.get(PATH, headers=token(key, "u"))
        assert response.status_code == 503
        assert response.json()["detail"] == {"code": "storage_unavailable"}
        assert response.headers["cache-control"] == "no-store"
