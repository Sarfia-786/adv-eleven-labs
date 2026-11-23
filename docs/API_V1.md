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
