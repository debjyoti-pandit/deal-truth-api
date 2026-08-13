# Contributing to OpenGong API

## Development setup

1. Install [Docker](https://docs.docker.com/get-docker/).
2. `make up` — `.env`, Postgres, Redis, SeaweedFS, migrations, API, and worker.

## Checks

```bash
make lint
make typecheck
make test-unit
```

Do not run live PyAI tests unless you have a sandbox key and set `RUN_PYAI_LIVE_TESTS=1`.

## Rules

- No customer audio or transcripts in the repo.
- No secrets in source, fixtures, or docs.
- Provider response shapes stay inside `app/providers/pyai/`.
- boto3 stays inside `app/storage/seaweed.py`.
- Factual insights must pass `app/evidence`.
- Retry only infrastructure failures.

Open a pull request with tests for new behavior.
