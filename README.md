# OpenGong API

Evidence-backed sales-call intelligence.

> **NO PROOF IN THE TRANSCRIPT, NO CLAIM IN THE REPORT.**

Upload a recording (or an HTTPS URL). OpenGong produces a diarized transcript, deterministic metrics, Customer Truth, Reality Check, Commitment Ledger, Deal Killers, a next-call battlecard, an evidence-safe follow-up email, and Ask-the-Call retrieval. Every factual claim points at real transcript segment IDs. Quotes are loaded from the transcript, never from a model.

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [all design docs](docs/README.md)

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL + pgvector · Celery · Redis · SeaweedFS (S3) · PyAI Hear/Recap · hosted `open-gong-ml`

Paid LLM providers are not used.

## Quick start (~2 minutes)

Prerequisite: [Docker](https://docs.docker.com/get-docker/).

```bash
make up
```

That creates `.env`, generates `SIGNED_URL_SECRET` and `PYAI_WEBHOOK_SECRET` if empty, mints a PyAI sandbox key into `PYAI_API_KEY` when that field is empty, then starts Postgres, Redis, SeaweedFS, ngrok, runs migrations, and runs the API + Celery worker in Docker. Existing env values are left unchanged. Secrets are never printed.

Set `NGROK_AUTHTOKEN` (or `NGROK_AUTH_TOKEN`) in `.env`. For a **stable public URL**, set `NGROK_DOMAIN` to your ngrok Dev Domain from [ngrok domains](https://dashboard.ngrok.com/domains) (for example `your-name.ngrok-free.app`). `make up` writes `NGROK_DOMAIN` after the first successful tunnel if it is empty, then later restarts bind that same hostname with `ngrok http --url`. Inspector: http://localhost:4040.

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

OpenAPI: http://localhost:8000/docs  
Architecture (from this machine): http://localhost:8000/api/v1/reference/ARCHITECTURE.md  
Doc catalog: http://localhost:8000/api/v1/reference

Stop with `make down`.

If port 8000 is already in use (for example a host `make api` process), stop that process first.

## Serving others (remote frontend)

`make up` publishes a stable HTTPS URL via ngrok (`NGROK_DOMAIN`, for example `https://your-name.ngrok-free.app`). Other machines use that host — not `localhost:8000`.

| What | URL |
|---|---|
| OpenAPI UI | `https://<NGROK_DOMAIN>/docs` |
| Doc catalog (JSON) | `https://<NGROK_DOMAIN>/api/v1/reference` |
| Architecture | `https://<NGROK_DOMAIN>/api/v1/reference/ARCHITECTURE.md` |
| Evidence | `https://<NGROK_DOMAIN>/api/v1/reference/evidence.md` |
| Providers | `https://<NGROK_DOMAIN>/api/v1/reference/providers.md` |
| Deterministic analysis | `https://<NGROK_DOMAIN>/api/v1/reference/deterministic-analysis.md` |
| Named errors | `https://<NGROK_DOMAIN>/api/v1/reference/named-errors.md` |
| Health | `https://<NGROK_DOMAIN>/health/live` |

Repo copies: [docs/README.md](docs/README.md).

Point the frontend `API_BASE_URL` at `https://<NGROK_DOMAIN>`. Add the frontend page origin to `CORS_ORIGINS` in `.env` (the ngrok HTTPS origin is included automatically). On ngrok’s free tier, browser calls should send header `ngrok-skip-browser-warning: true`.

`AUTH_MODE=none` plus a public ngrok URL means anyone with the host can call the API. Dev only.

### Host processes (optional)

Python 3.12 and [uv](https://docs.astral.sh/uv/) required. Infra still runs in Docker; API and worker run on the host:

```bash
make setup
make api      # terminal 1
make worker   # terminal 2
```

`make worker` does **not** take `--acks-late`. Late acks are set in `app/tasks/celery_app.py` (`task_acks_late=True`).

## PyAI sandbox key

`make up` / `make setup` call `POST https://api.pyai.com/v1/sandbox/keys` (no auth) when `PYAI_API_KEY` is empty, then write the key to `.env`. See [mint a sandbox key](https://docs.pyai.com/api-reference/sandbox/mint-a-sandbox-key-no-auth). The running API process does **not** mint or print keys.

- Existing `PYAI_API_KEY` values are never overwritten.
- A 429/404 from the mint endpoint is retried, then skipped so `make up` still starts the stack.
- Set `PYAI_SKIP_SANDBOX_MINT=1` to skip minting (offline).
- Compose runs **ngrok** so PyAI can reach this machine. The worker prefers the webhook (`POST /api/v1/webhooks/pyai/transcription`) and falls back to bounded polling if the tunnel is down.
- `PUBLIC_API_BASE_URL` stays `http://localhost:8000` for local browsers. PyAI-facing `audio_url` and `webhook_url` use the ngrok HTTPS URL.
- `PYAI_AUDIO_INPUT_MODE=audio_url` issues a short-lived HMAC-signed OpenGong URL. PyAI never receives SeaweedFS credentials.
- `PYAI_RECAP_PACK_ID=sales_outbound` by default. Recap failure leaves the transcript intact and finishes `PARTIAL`.

Live tests (not CI):

```bash
RUN_PYAI_LIVE_TESTS=1 uv run pytest tests/live -q
```

## Tests

```bash
make check    # all routes, in-process (before the server)
make smoke    # all routes against http://localhost:8000
```

`make up` runs `check` before Docker starts, then `smoke` after the API is healthy.

Fixtures under `fixtures/` are synthetic. Do not commit customer audio or transcripts.

## Auth

- `AUTH_MODE=none` — local/dev only
- `AUTH_MODE=api_key` — send `Authorization: Bearer <key>` or `X-API-Key`

## License

MIT. See [LICENSE](LICENSE), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md).
