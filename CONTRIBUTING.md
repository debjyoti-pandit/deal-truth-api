# Contributing to Deal Truth API

## Naming

Use the form that the host system allows. Do not flatten to `dealtruth`.

| Context | Form | Examples |
|---|---|---|
| Humans, LICENSE, API title | Deal Truth | Deal Truth API |
| Repo, PyPI, Docker, env `APP_NAME`, S3, Redis keys, files | `deal-truth` | `deal-truth:local`, `deal-truth-audio` |
| Python modules, Celery, Postgres user/db | `deal_truth` | `deal_truth.process_call` |
| Classes | PascalCase | `DealTruthMLClient` |
| Env var names | `DEAL_TRUTH_*` | `DEAL_TRUTH_BASE_URL` |

Hyphens are invalid in Python identifiers and unquoted Postgres names, so those stay snake_case.

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
