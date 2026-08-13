# Third-party licenses

This project is MIT licensed. Runtime dependencies include (non-exhaustive):

| Package | Typical license |
|---|---|
| FastAPI | MIT |
| Pydantic | MIT |
| SQLAlchemy | MIT |
| Alembic | MIT |
| asyncpg | Apache-2.0 |
| psycopg | LGPL-3.0 |
| pgvector | PostgreSQL / MIT |
| Celery | BSD-3-Clause |
| redis-py | MIT |
| boto3 | Apache-2.0 |
| httpx | BSD-3-Clause |
| uvicorn | BSD-3-Clause |
| sse-starlette | BSD-3-Clause |

PyAI, SeaweedFS, PostgreSQL, Valkey, and the hosted `open-gong-ml` models are used at runtime and keep their own licenses.

Generate a locked inventory with:

```bash
uv export --frozen --no-dev --format requirements-txt
```
