# Deal Truth API design docs

These files are the product and architecture reference. The running API also serves them at `/api/v1/reference` (and `/api/v1/reference/{name}`) so a remote frontend or another machine on the ngrok URL can read them without cloning the repo.

| Doc | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System layout, pipeline, invariants, deploy |
| [evidence.md](evidence.md) | Evidence statuses, quote rules, speaker roles |
| [providers.md](providers.md) | Provider interfaces (PyAI, ML, blob store) |
| [deterministic-analysis.md](deterministic-analysis.md) | Metrics and rules that are not model-generated |
| [named-errors.md](named-errors.md) | Stable error codes for clients |
| [frontend-contract.md](frontend-contract.md) | Frontend gap resolutions: NOT_READY, SSE shape, audio-url, search, share URLs |
| [examples/](examples/) | SHIPPED `report`/`insights`/`metrics`/`events`/`transcript` sample payloads (synthetic fixture) |

OpenAPI UI on a running instance: `/docs`.
