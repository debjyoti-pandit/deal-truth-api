# Deal Truth API — deploy in one hour

Pair with `deal-truth-ml` [docs/DEPLOYMENT.md](../../deal-truth-ml/docs/DEPLOYMENT.md).

## Local (both apps talking)

```bash
# ML
cd deal-truth-ml && cp .env.example .env && make up

# API
cd deal-truth && cp .env.example .env && make up
```

Fill **you must add** (not in Git, not generated):

| Where | Var | Get it from |
|---|---|---|
| both `.env` | `NGROK_AUTHTOKEN` | https://dashboard.ngrok.com/get-started/your-authtoken |
| `deal-truth/.env` | `NGROK_DOMAIN` | API Dev Domain — https://dashboard.ngrok.com/domains |
| `deal-truth-ml/.env` | `NGROK_DOMAIN` | **Different** ML Dev Domain |
| host | Cloudflare login | `cd deal-truth-ml && make login` (or `CLOUDFLARE_API_TOKEN`) |

`make up` in the API mints PyAI sandbox key and HMAC secrets if empty.

Local ML URL (already in `.env.example`): `ML_SERVICE_BASE_URL=http://host.docker.internal:8081`.

If the API cannot see the Mac (Linux VM / Oracle), set `ML_SERVICE_BASE_URL` to the ML ngrok HTTPS URL from `deal-truth-ml make up`.

Then `make restart` on the API.

## Production (Oracle VM + Workers AI + Pages)

Use `.env.production.example` on the VM as `.env`.

### 1. Deploy ML first

```bash
cd deal-truth-ml
npx wrangler secret put INTERNAL_API_TOKEN   # generate a long random token
npx wrangler deploy
# note the https://deal-truth-ml.<subdomain>.workers.dev URL
```

Optional: `CLOUDFLARE_ACCOUNT_ID` for CI (dashboard sidebar). Model IDs are in `wrangler.jsonc`.

### 2. Fill API `.env` on the Oracle VM

Copy `.env.production.example`. You must fill:

| Var | What |
|---|---|
| `PUBLIC_API_BASE_URL` | `https://` API host (Caddy) |
| `AUTH_MODE=api_key` + `API_KEYS` | do not leave `none` on a public host |
| `CORS_ORIGINS` | `https://<pages-host>` |
| `DATABASE_URL` / `DATABASE_SYNC_URL` | Supabase URI |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Valkey on the VM |
| `S3_*` | Supabase Storage S3 or SeaweedFS |
| `PYAI_API_KEY` / `PYAI_WEBHOOK_SECRET` | PyAI dashboard |
| `ML_SERVICE_BASE_URL` | Worker URL from step 1 |
| `ML_SERVICE_API_KEY` | **same** as `INTERNAL_API_TOKEN` |
| `SIGNED_URL_SECRET` | random 32+ bytes |

Set `NGROK_ENABLED=false` if Caddy is public.

### 3. Web

`VITE_API_BASE_URL=https://<PUBLIC_API_BASE_URL host>`

### 4. Bring API up

```bash
make up
# or docker compose on the VM with production .env
```

Health: `GET /health/ready` must show DB + blob. A call pipeline needs ML 200s on `POST /classify`.
