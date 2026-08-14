# Deploy Deal Truth API on Render (laptop SeaweedFS)

Render runs the **API + Celery worker**. Postgres and Redis are Render add-ons.
Object storage stays on **this machine**: Docker SeaweedFS, published with ngrok.

The laptop must stay awake. If Seaweed or the tunnel dies, uploads and reports fail.

## One-time: Render services

1. **PostgreSQL** — create a database. Use the **Internal** URL on Render (host like `dpg-…-a`).
2. **Key Value (Redis)** — same region as the web service. Copy **Internal Redis URL**.
3. **Web** service (this repo)
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Pre-deploy: `alembic upgrade head`
4. **Background Worker** (same repo, same env)
   - Start: `celery -A app.tasks.celery_app worker --loglevel=info`
5. In Render Postgres **PSQL**, once:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Then run the pre-deploy migrate (or redeploy).

## Every time you need storage from Render

```bash
make up-local          # Seaweed in Docker
make seaweed-tunnel    # Docker ngrok-seaweed (background, restart unless-stopped)
```

`make up` / `make up-local` start `ngrok-seaweed` with the rest of the stack. Inspector: http://127.0.0.1:4042

Render `S3_ENDPOINT_URL` is always `https://deal-truth-seaweed.ngrok-free.app`.
Do not use the API domain `deal-truth-ngrok.ngrok-free.app` for S3.

## Render environment

Paste into **Environment**. Replace `REPLACE_*` and the Seaweed ngrok host after `make seaweed-tunnel`.

Do not commit real passwords. Internal `dpg-` / `red-` hosts only work **inside Render**.

```bash
APP_NAME=deal-truth-api
APP_ENV=production
LOG_LEVEL=INFO
LOG_FORMAT=json

PUBLIC_API_BASE_URL=https://REPLACE_RENDER_WEB.onrender.com
PUBLIC_WEB_BASE_URL=https://REPLACE_WEB_APP
NGROK_ENABLED=false

AUTH_MODE=api_key
API_KEYS=REPLACE_LONG_RANDOM_API_KEY
CORS_ORIGINS=https://REPLACE_WEB_APP

DATABASE_URL=postgresql+asyncpg://REPLACE_DB_USER:REPLACE_DB_PASSWORD@REPLACE_DPG_HOST/deal_truth?ssl=require
DATABASE_SYNC_URL=postgresql+psycopg://REPLACE_DB_USER:REPLACE_DB_PASSWORD@REPLACE_DPG_HOST/deal_truth?sslmode=require

CELERY_BROKER_URL=redis://REPLACE_RED_HOST:6379/0
CELERY_RESULT_BACKEND=redis://REPLACE_RED_HOST:6379/1

S3_ENDPOINT_URL=https://deal-truth-seaweed.ngrok-free.app
S3_ACCESS_KEY=REPLACE_SEAWEED_ACCESS_KEY
S3_SECRET_KEY=REPLACE_SEAWEED_SECRET_KEY
S3_REGION=us-east-1
S3_BUCKET_AUDIO=deal-truth-audio
S3_BUCKET_RESULTS=deal-truth-results
S3_BUCKET_SAMPLES=deal-truth-samples
S3_USE_SSL=true
S3_ADDRESSING_STYLE=path

MAX_AUDIO_BYTES=524288000
ALLOWED_AUDIO_MIME_TYPES=audio/mpeg,audio/wav,audio/x-wav,audio/wave,audio/mp4,audio/ogg,audio/webm,audio/flac,audio/x-m4a,video/mp4
ALLOWED_AUDIO_EXTENSIONS=.mp3,.wav,.m4a,.ogg,.webm,.flac,.mp4

PYAI_API_KEY=REPLACE_PYAI_API_KEY
PYAI_BASE_URL=https://api.pyai.com/v1
PYAI_WEBHOOK_SECRET=REPLACE_PYAI_WEBHOOK_SECRET
PYAI_RECAP_ENABLED=true
PYAI_TRACE_ENABLED=false
PYAI_RECAP_PACK_ID=sales_outbound
PYAI_AUDIO_INPUT_MODE=audio_url
PYAI_POLL_INTERVAL_SECONDS=5
PYAI_POLL_DEADLINE_SECONDS=1800

ML_SERVICE_BASE_URL=https://deal-truth-ml.onrender.com
ML_SERVICE_API_KEY=REPLACE_ML_INTERNAL_TOKEN
ML_MAX_BATCH_SIZE=32
ML_GENERATION_ENABLED=true

SIGNED_URL_TTL_SECONDS=900
SIGNED_URL_SECRET=REPLACE_SIGNED_URL_SECRET
SHARE_TOKEN_TTL_SECONDS=604800
STEREO_DEFAULT_CHANNEL_SELLER=0
CONFIDENCE_THRESHOLD=0.5
SOURCE_FETCH_TIMEOUT_SECONDS=30
SOURCE_FETCH_MAX_REDIRECTS=3
SLACK_WEBHOOK_HOSTS=hooks.slack.com
```

If internal Postgres SSL fails, drop `?ssl=require` / `?sslmode=require`.

Local `.env` `S3_ENDPOINT_URL` stays `http://localhost:8333` (or `http://seaweedfs:8333` in Compose). Only Render uses the ngrok Seaweed URL.

## Checks

```bash
curl -sS https://REPLACE_RENDER_WEB.onrender.com/health/ready
```

Expect `"status":"ready"` and `"workers": 1`. Upload a call; the object should appear in local Seaweed (`localhost:8333`).
