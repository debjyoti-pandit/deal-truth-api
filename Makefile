.PHONY: install lock lint fmt format typecheck test test-unit test-live migrate migrate-check api worker flower docker-build compose-up compose-down openapi setup infra infra-local up up-local down restart restart-local reset-db truncate check smoke hooks

UV ?= uv
NPM ?= npm

# Local compose: Docker Postgres + forced local DATABASE_* (does not change .env).
COMPOSE_LOCAL := docker compose --profile local-db -f docker-compose.yml -f docker-compose.local.yml

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

# Infra only (DB from .env / Supabase). Redis + object store + ngrok.
infra:
	docker compose up -d --wait redis seaweedfs ngrok

# Infra with local Docker Postgres (host processes can use localhost:5432).
infra-local:
	$(COMPOSE_LOCAL) up -d --wait postgres redis seaweedfs ngrok

setup: install
	$(UV) run python scripts/bootstrap_env.py
	$(MAKE) infra
	$(UV) run alembic upgrade head
	@echo ""
	@echo "Infra is up. For host processes: make api  and  make worker"
	@echo "Docker (DB from .env / Supabase): make up"
	@echo "Docker (all local Postgres):     make up-local"

check:
	$(UV) run python scripts/check_endpoints.py --in-process

smoke:
	$(UV) run python scripts/check_endpoints.py --base-url http://localhost:8000

# Full stack; DATABASE_* from .env (Supabase Session pooler when configured).
up:
	bash scripts/docker_up.sh --env

# Full stack on local Docker Postgres (overrides .env DATABASE_* inside compose only).
up-local:
	bash scripts/docker_up.sh --local

# Bounce API/worker/ngrok without wiping DB. Uses .env DATABASE_* (e.g. Supabase).
restart:
	docker compose run --rm --build migrate
	docker compose up -d --build --force-recreate --no-deps api worker flower ngrok

# Same bounce against local Docker Postgres.
restart-local:
	$(COMPOSE_LOCAL) run --rm --build migrate
	$(COMPOSE_LOCAL) up -d --build --force-recreate --no-deps api worker flower ngrok

down:
	docker compose --profile local-db -f docker-compose.yml -f docker-compose.local.yml down --remove-orphans

# Recreate local Docker Postgres volume (OpenGong → deal_truth / wipe data).
reset-db:
	$(COMPOSE_LOCAL) stop postgres migrate api worker || true
	$(COMPOSE_LOCAL) rm -f postgres migrate || true
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
