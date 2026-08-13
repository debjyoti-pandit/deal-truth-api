.PHONY: install lock lint fmt format typecheck test test-unit test-live migrate migrate-check api worker flower docker-build compose-up compose-down openapi setup infra up down restart reset-db truncate check smoke hooks

UV ?= uv
NPM ?= npm

install:
	$(UV) sync --extra dev
	$(NPM) install
	$(NPM) run prepare

hooks:
	$(NPM) install
	$(NPM) run prepare
	@echo "Husky hooks installed (pre-commit: ruff; commit-msg: commitlint)"

lock:
	$(UV) lock

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt format:
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck:
	$(UV) run mypy app tests

test:
	$(UV) run pytest tests/unit tests/contract tests/integration -q

test-unit:
	$(UV) run pytest tests/unit tests/contract -q

test-live:
	RUN_PYAI_LIVE_TESTS=1 $(UV) run pytest tests/live -q

migrate:
	$(UV) run alembic upgrade head

migrate-check:
	$(UV) run alembic check
	$(UV) run alembic upgrade head --sql > /tmp/deal-truth-api-migration.sql

infra:
	docker compose up -d --wait postgres redis seaweedfs ngrok

setup: install
	$(UV) run python scripts/bootstrap_env.py
	$(MAKE) infra
	$(UV) run alembic upgrade head
	@echo ""
	@echo "Infra is up. For host processes: make api  and  make worker"
	@echo "For everything in Docker: make up"

check:
	$(UV) run python scripts/check_endpoints.py --in-process

smoke:
	$(UV) run python scripts/check_endpoints.py --base-url http://localhost:8000

up:
	bash scripts/docker_up.sh

# Bounce API/worker/ngrok without wiping Postgres. Applies pending Alembic first
# (needed when ML embeddings change dimension).
restart:
	docker compose run --rm --build migrate
	docker compose up -d --build --force-recreate --no-deps api worker flower ngrok

down:
	docker compose down --remove-orphans

# Recreate Postgres after credential/name changes (OpenGong → deal_truth).
reset-db:
	docker compose stop postgres migrate api worker || true
	docker compose rm -f postgres migrate || true
	docker volume rm deal-truth_postgres_deal_truth deal-truth_postgres_data 2>/dev/null || true

truncate:
	$(UV) run python scripts/truncate_db.py --yes

api: check
	$(UV) run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	# acks_late is configured on the Celery app (task_acks_late); it is not a CLI flag.
	$(UV) run celery -A app.tasks.celery_app worker --loglevel=info

flower:
	$(UV) run celery -A app.tasks.celery_app flower --address=127.0.0.1 --port=5555

docker-build:
	docker build -t deal-truth-api:local .

compose-up: up

compose-down: down

openapi:
	$(UV) run python scripts/export_openapi.py
