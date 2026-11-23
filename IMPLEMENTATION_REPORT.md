# Voice Engine implementation checkpoint

The first feature lets Repo 1 retrieve the authenticated user's Free or Premium policy over HTTP. Its example pull request is [#3](https://github.com/Sarfia-786/adv-eleven-labs/pull/3). The tenant-owned persistence work for [issue #4](https://github.com/Sarfia-786/adv-eleven-labs/issues/4) is on `feature/hosted-ownership`. The [tracker](https://github.com/Sarfia-786/adv-eleven-labs/issues/2) records dependencies and checkpoint commits.

## Tenant-owned persistence

Issue #4 adds create, list, read, replace and delete for named pronunciation dictionaries. Each database operation uses the verified issuer and subject. Premium users can save respellings. A user who downgrades can still retrieve and delete their data. The hosted Alembic chain starts at `h0001` with its own version table. Database configuration, startup, backup and rollback are in [API v1](docs/API_V1.md#tenant-owned-pronunciation-dictionaries).

On Linux CPU with Python 3.12 and an empty model cache, **81 focused tests passed**. The tests exercised actual signed HTTP requests, a new app instance opening saved data, identical foreign and unknown resource errors, populated Studio profiles/gallery/history across repeated upgrades, and hosted rollback. Ruff and the offline lock check passed. PostgreSQL DDL can be rendered with the command below. A live PostgreSQL migration and CRUD round trip remain to be verified. Audio generation with these dictionaries is tracked in #14. The next dependent issue is [private audio storage #5](https://github.com/Sarfia-786/adv-eleven-labs/issues/5).

```sh
HF_HUB_OFFLINE=1 HF_HUB_CACHE="$(mktemp -d)" python -m pytest -q \
  tests/test_hosted_ownership.py tests/test_hosted_entitlements.py tests/test_auth_principal.py \
  tests/test_db_migration_safety.py tests/test_db_schema_reconcile.py tests/test_list_sort_indexes_migration.py \
  tests/test_changelog_fragments.py tests/test_issue_template_labels.py
VOICE_API_DATABASE_URL=postgresql+psycopg://localhost/voice alembic -c alembic-hosted.ini upgrade head --sql
uv lock --check --offline --python python3.12
```

## Entitlements on the reference branch

| Area | Implementation |
| --- | --- |
| Hosted entry point | `backend/hosted_api.py` exposes `GET /api/v1/entitlements` and the hosted OpenAPI schema. The original Studio listener serves the existing local and OpenAI routes. |
| Identity and policy | `backend/services/hosted_identity.py` verifies Repo 1's short-lived signed assertions. `backend/services/hosted_entitlements.py` maps the trusted plan to subscription capabilities. |
| Dependencies and data | `pyproject.toml` and `uv.lock` declare PyJWT with its cryptography extra directly. The read-only lookup needs no database migration, object storage, worker or model. |
| Contract and handoff | `docs/API_V1.md` gives startup commands, environment settings, claim definitions, responses and errors. `docs/ADV_ELEVEN_LABS_AUDIT.md` identifies reusable services. The hosted feature issue form and the PR show how to hand work to the next contributor. |

## Entitlement verification

On Linux CPU with Python 3.12, FastAPI 0.136.3 and PyJWT 2.15.0, the following focused run passed **57 tests** with the model cache empty. The test client emitted a Starlette deprecation warning.

```sh
HF_HUB_OFFLINE=1 HF_HUB_CACHE="$(mktemp -d)" python -m pytest -q \
  tests/test_hosted_entitlements.py tests/test_auth_principal.py \
  tests/test_changelog_fragments.py tests/test_issue_template_labels.py
ruff check backend/hosted_api.py backend/services/hosted_identity.py \
  backend/services/hosted_entitlements.py tests/test_hosted_entitlements.py
uv lock --check --offline --python python3.12
```

Ruff and the offline lock check passed. A separate live Uvicorn process served the published OpenAPI document, returned HTTP 200 for a real RSA-signed Premium assertion, and rejected an unauthenticated loopback request with HTTP 401.

## Entitlement deployment

For a development run, configure the issuer, audience, service identity and verification key as described in [API v1](docs/API_V1.md). Repo 1 must supply its own signing key and verified billing decision. The response describes policy; each feature's issue tracks implementation and runtime availability. This checkpoint covers a read-only hosted endpoint. Deployment of the full service, migrations, audio inference, CPU/GPU worker operation, model-license clearance, frontend builds and end-to-end acceptance remain with the linked features. See [the baseline audit](docs/ADV_ELEVEN_LABS_AUDIT.md) and [implementation tracker](https://github.com/Sarfia-786/adv-eleven-labs/issues/2).
