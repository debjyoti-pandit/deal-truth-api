# Contributing to Deal Truth API

## Naming

Use the form that the host system allows. Do not flatten to `dealtruth`.

| Context | Form | Examples |
|---|---|---|
| Humans, LICENSE, OpenAPI title | Deal Truth API | Deal Truth API |
| GitHub repo, PyPI, Docker image, env `APP_NAME` | `deal-truth-api` | `deal-truth-api:local` |
| Product S3 buckets, Redis key prefix | `deal-truth` | `deal-truth-audio` |
| Sibling repos | `deal-truth-web`, `deal-truth-ml` | UI and hosted ONNX service |
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

## Git hooks (Husky)

Requires Node.js 18+. One-time (also runs via `make install`):

```bash
make hooks
```

| Hook | What it runs |
|---|---|
| `pre-commit` | `lint-staged` → `ruff check --fix` + `ruff format` on staged `*.py` |
| `commit-msg` | `commitlint` (conventional commits, e.g. `fix: …`, `feat: …`) |

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/). Emoji at the end of the subject is fine.

Bypass only when necessary: `HUSKY=0 git commit …` (do not use for routine work).

Do not run live PyAI tests unless you have a sandbox key and set `RUN_PYAI_LIVE_TESTS=1`.

## Rules

- No customer audio or transcripts in the repo.
- No secrets in source, fixtures, or docs.
- Provider response shapes stay inside `app/providers/pyai/`.
- boto3 stays inside `app/storage/seaweed.py`.
- Factual insights must pass `app/evidence`.
- Retry only infrastructure failures.

Open a pull request with tests for new behavior.
