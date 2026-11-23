# Voice Engine implementation checkpoint

The first feature lets Repo 1 retrieve the authenticated user's Free or Premium policy over HTTP. Its example pull request is [#3](https://github.com/Sarfia-786/adv-eleven-labs/pull/3). The next feature is [tenant-owned persistence](https://github.com/Sarfia-786/adv-eleven-labs/issues/4). The [tracker](https://github.com/Sarfia-786/adv-eleven-labs/issues/2) records dependencies and checkpoint commits.

## What shipped on the feature branch

| Area | Implementation |
| --- | --- |
| Hosted entry point | `backend/hosted_api.py` exposes `GET /api/v1/entitlements` and the hosted OpenAPI schema. The original Studio listener serves the existing local and OpenAI routes. |
| Identity and policy | `backend/services/hosted_identity.py` verifies Repo 1's short-lived signed assertions. `backend/services/hosted_entitlements.py` maps the trusted plan to subscription capabilities. |
| Dependencies and data | `pyproject.toml` and `uv.lock` declare PyJWT with its cryptography extra directly. The read-only lookup needs no database migration, object storage, worker or model. |
| Contract and handoff | `docs/API_V1.md` gives startup commands, environment settings, claim definitions, responses and errors. `docs/ADV_ELEVEN_LABS_AUDIT.md` identifies reusable services. The hosted feature issue form and the PR show how to hand work to the next contributor. |

## Verification

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

## Resume and deployment

For a development run, configure the issuer, audience, service identity and verification key as described in [API v1](docs/API_V1.md). Repo 1 must supply its own signing key and verified billing decision. The response describes policy; each feature's issue tracks implementation and runtime availability. This checkpoint covers a read-only hosted endpoint. Deployment of the full service, migrations, audio inference, CPU/GPU worker operation, model-license clearance, frontend builds and end-to-end acceptance remain with the linked features. See [the baseline audit](docs/ADV_ELEVEN_LABS_AUDIT.md) and [implementation tracker](https://github.com/Sarfia-786/adv-eleven-labs/issues/2).
