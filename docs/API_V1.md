# Hosted Voice API v1

The hosted ASGI listener serves Repo 1. Start it on a private interface with a configured public verification key. Terminate external HTTPS at the deployment proxy. Desktop and OpenAI clients continue to use the Studio server.

```sh
export VOICE_API_PUBLIC_KEY_FILE=/run/keys/repo1-public.pem
export VOICE_API_ISSUER=repo1
export VOICE_API_AUDIENCE=voice-api
export VOICE_API_SERVICE_ID=repo1-backend
uv run uvicorn --app-dir backend hosted_api:create_app --factory --host 127.0.0.1 --port 3901
```

Repo 1 authenticates the user and reads their subscription before issuing a bearer JWT. Sign with RS256 and retain the private key at Repo 1. The gateway reads a pinned RSA public PEM (2048 bits or larger) at startup. Rotate the key by deploying the new public key and restarting the gateway in coordination with the issuer. Use a dedicated issuer/key and audience for service assertions.

| Signed claim | Value |
| --- | --- |
| `iss`, `aud`, `azp` | Configured issuer, API audience and calling service ID |
| `sub` | Stable nonempty user ID within the configured issuer |
| `iat`, `exp` | Unix seconds, integers, with lifetime from 1 to 300 seconds |
| `scope` | Space-separated permissions, including `entitlements:read` for this route |
| `plan` | `free` or `premium`. Set `VOICE_API_PLAN_CLAIM` to read another signed claim name. |

```sh
curl --fail-with-body -H "Authorization: Bearer ${SERVICE_TOKEN}" \
  http://127.0.0.1:3901/api/v1/entitlements
```

A Free response is `{"api_version":"v1","subject":"user-a","plan":"free","capabilities":["basic_speech"]}`. The sorted capabilities describe subscription policy. The current operation surface is published at `/openapi.json`. An invalid or expired token returns HTTP 401 with `detail.code=invalid_token`. A valid token without the scope returns HTTP 403 with `detail.code=insufficient_scope`. Refresh expired credentials at the issuer. Clients must obtain the appropriate grant before retrying a 403.

## Request IDs

Each hosted HTTP response carries one `X-Request-ID`, including authentication errors, missing routes and server errors. Repo 1 can supply an opaque identifier up to 64 ASCII characters. Start with a letter or digit and use letters, digits, periods, underscores or hyphens thereafter. A missing, invalid or repeated header produces a new 32-character hexadecimal ID. Send only an identifier in this header.

Use the response ID to locate the matching `hosted_request_completed` event in the `uvicorn.error.hosted_requests` logger. Its structured fields are `request_id` and `status_code`. If the server never starts a response, the status field is null. Application code can read the same ID from `request.state.request_id` or the current request context. Authentication, request bodies, URLs and query strings are excluded from this diagnostic event.

## Tenant-owned pronunciation dictionaries

Repo 1 can save named word or phrase respellings for the signed user. The owner key is the SHA-256 digest of the ASCII JSON encoding of the verified `[iss, sub]` pair with compact separators. A signing-key rotation preserves ownership. A change of issuer creates a separate namespace. The database primary key starts with the owner key. Every lookup and mutation uses it, including list queries.

| Method and path under `/api/v1` | Signed scope | Result |
| --- | --- | --- |
| `POST /pronunciation-dictionaries` | `dictionaries:write` | Premium creates a dictionary, HTTP 201 |
| `GET /pronunciation-dictionaries?limit=50&offset=0` | `dictionaries:read` | Paginated `items` containing the user's IDs and names, ordered by ID. Maximum page size is 100. |
| `GET /pronunciation-dictionaries/{id}` | `dictionaries:read` | Dictionary ID, name, entries and API version |
| `PUT /pronunciation-dictionaries/{id}` | `dictionaries:write` | Premium replaces the name and complete entry map, HTTP 200 |
| `DELETE /pronunciation-dictionaries/{id}` | `dictionaries:write` | Deletes an owned dictionary, HTTP 204 |

Create or replace with `{"name":"Studio","entries":{"SQL":"sequel"}}`. A dictionary can have up to 256 mappings, with 200 characters per term or replacement and 120 per name. Lists and individual records include `api_version: "v1"`. After a downgrade, users can still read and delete their own dictionaries. A foreign or unknown UUID returns the same HTTP 404. Missing storage or an unapplied migration returns HTTP 503 with `detail.code=storage_unavailable`. Issue #14 covers applying a saved dictionary during generation.

### Database setup and recovery

Set `VOICE_API_DATABASE_URL` for both Alembic and the hosted process. Use a separate database for the service. The existing read-only entitlement endpoint can operate without database configuration.

For local development, set `VOICE_API_DATABASE_URL=sqlite:////absolute/path/hosted.db` with a writable parent directory and SQLite 3.35 or later. From the repository root, run the migration before starting the listener.

```sh
uv run alembic -c alembic-hosted.ini upgrade head
uv run uvicorn --app-dir backend hosted_api:create_app --factory --host 127.0.0.1 --port 3901
```

For PostgreSQL, set a `postgresql+psycopg://` connection URL through the deployment's secret configuration. Supply the Psycopg 3 driver in the hosted environment for both commands, e.g. with `uv run --with 'psycopg[binary]>=3.2,<4'`. Run one migrator per deployment before starting API replicas. The hosted revision table is `hosted_alembic_version`. Studio continues to run its own migrations.

Before upgrading, make a consistent backup. For SQLite use `sqlite3 /absolute/path/hosted.db ".backup '/absolute/path/hosted-before.db'"`. For PostgreSQL use `pg_dump -Fc -f hosted-before.dump` with libpq connection settings for the hosted database. For an application rollback, stop hosted writes and revert the app first. The entitlement-only version can run with the added tables in place. To undo the first schema revision, `uv run alembic -c alembic-hosted.ini downgrade base` drops every hosted dictionary. Restore saved dictionaries from the backup into a fresh database and verify it before switching the service's database URL.

## Reviewing the hosted OpenAPI contract

Repo 1 clients can inspect the hosted listener in [hosted-openapi.json](hosted-openapi.json). The exporter calls `hosted_api.create_app()` with a temporary public verification key and storage disabled. You can run it offline without configuring a service or starting a listener. The Studio and mobile schema has its own exporter in `scripts/export_openapi.py`.

From the repository root, compare the current app with the published contract. The check prints a unified diff to stderr and exits with status 1 on drift. To inspect another branch's published schema, pass its file after `--check`.

```sh
uv run python scripts/export_hosted_openapi.py --check
jq '.paths["/api/v1/entitlements"].get | {operationId, security, response: .responses["200"].content["application/json"].schema}' docs/hosted-openapi.json
jq '.components.securitySchemes.Repo1ServiceToken' docs/hosted-openapi.json
jq '.paths["/api/v1/pronunciation-dictionaries"].post.requestBody, .components.schemas.DictionaryInput.required' docs/hosted-openapi.json
```

For an intentional change, regenerate the baseline, inspect the diff for affected clients, and commit it with the route change. Omitting `--output` writes the schema to stdout.

```sh
uv run python scripts/export_hosted_openapi.py --output docs/hosted-openapi.json
git diff -- docs/hosted-openapi.json
uv run python -m pytest -q tests/test_hosted_openapi_contract.py
```

## Private audio artifacts

Repo 1 or a worker chooses a fresh UUID for each logical audio result. Call these endpoints with the scoped token for its owner. The gateway streams the bytes from a private directory or S3 bucket. The upload returns a relative, expiring `download_path`. Use that path to retrieve or delete this upload. An old path remains expired if the UUID is reused after cleanup.

| Method and path under `/api/v1` | Signed scope | Contract |
| --- | --- | --- |
| `PUT /artifacts/{uuid}` | `artifacts:write` | Raw `audio/wav` or `audio/mpeg` body. Returns 201 with `id`, `media_type`, `size_bytes`, `expires_at` (Unix seconds), `download_path` and `api_version`. |
| `GET /artifacts/{uuid}?expires_at={expiry}` | `artifacts:read` | Downloads the owned audio with its measured length, an attachment filename, `nosniff` and `no-store`. Foreign, unknown, expired and deleted IDs return the same 404. |
| `DELETE /artifacts/{uuid}?expires_at={expiry}` | `artifacts:write` | Returns 204 for a successful or already satisfied deletion. An unavailable store returns 503 and retrieval is disabled while deletion awaits retry. |

```sh
curl --fail-with-body -X PUT -H "Authorization: Bearer ${SERVICE_TOKEN}" \
  -H 'Content-Type: audio/wav' --data-binary @speech.wav \
  "${VOICE_API}/api/v1/artifacts/${ARTIFACT_ID}" -o receipt.json
DOWNLOAD_PATH=$(jq -er '.download_path' receipt.json)
curl --fail-with-body -H "Authorization: Bearer ${SERVICE_TOKEN}" \
  "${VOICE_API}${DOWNLOAD_PATH}" -o received.wav
```

Retry identical bytes and MIME type at the same UUID after a timeout. A replay returns 200 and the original expiry. Reusing that UUID for different audio returns 409. An interrupted upload stays private. Recoverable storage failures return 503. Oversized bodies return 413 and invalid audio returns 415. A second tenant may use the same UUID for its own independent artifact.

### Storage configuration and retention

Apply `uv run alembic -c alembic-hosted.ini upgrade head` to install revision `h0002`. Use the same database, bucket or filesystem, limits and clock settings on the API and cleanup processes.

| Setting | Value |
| --- | --- |
| `VOICE_ARTIFACT_BACKEND` | `local` or `s3`. Omit to leave artifact storage unconfigured. |
| `VOICE_ARTIFACT_DIR` | Absolute private directory for local mode. Grant access only to the service account and keep it outside any static web root. |
| `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ENDPOINT` | For S3, provide a dedicated private **unversioned** bucket. The optional endpoint selects an S3-compatible service. Use HTTPS for remote storage. |
| AWS credentials and region | Use the standard Boto3 credential and region settings, preferably a workload role. Allow `GetBucketVersioning` on the bucket and `GetObject`, `PutObject`, `DeleteObject` on `artifacts/*`. Enable bucket public-access blocking. |
| `VOICE_ARTIFACT_MAX_BYTES` | Per upload, default 32 MiB, maximum 256 MiB. The gateway counts bytes as it receives them. |
| `VOICE_ARTIFACT_TTL_SECONDS` | From the first reservation, default 86,400 seconds. Allowed range 1 second to 30 days. |

Run the cleanup command periodically, for example once per minute using the deployment scheduler. Access ends at expiry. Physical deletion runs in batches and failed deletions are retried on later sweeps. Size the batch and frequency for the upload rate, monitor nonzero exits and configure a bucket lifecycle backstop. Keep the operating system's private temporary directory on a volume with sufficient space for simultaneous uploads and with age-based cleanup for abandoned process files.

```sh
PYTHONPATH=backend uv run python -m services.hosted_artifacts --limit 100
```

Before downgrading below `h0002`, stop writes and back up the database and its matching private objects. Apply the retention policy or export required artifacts before removing their metadata. Restore both backups together when recovering the service. The first implementation provides authenticated downloads for local storage and S3. Job submission and publishing generated results use this interface in the dependent job and speech issues.
