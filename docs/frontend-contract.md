# Frontend contract notes (deal-truth-web)

Resolutions for `BACKEND_API_GAPS_AND_RESOLUTIONS.md`. Wire payloads are snake_case; the web
client adapts to camelCase.

## Readiness and NOT_READY (GAP-BE-001/002/003)

`GET /calls/{id}/report`, `GET /calls/{id}/export/json|markdown`, and `GET /shared/{token}`
return the standard error envelope with **HTTP 409, code `NOT_READY`, `retryable: true`** until
the call status is `SHIPPED` or `PARTIAL`. They never return a bare 500 for an unready call.
Blob-store failures on a ready call surface as `BLOB_DOWNLOAD_FAILED` (502).

`GET /shared/{token}` for a ready call returns `{ "report": {...}, "transcript": {...} }`
(transcript is the same shape as `GET /calls/{id}/transcript`).

## Report document (GAP-BE-009)

Committed samples generated from the synthetic fixture pipeline (regenerate with
`uv run python scripts/generate_report_examples.py`):

- `docs/examples/report.shipped.json` — full `GET /report` body (snake_case, `evidence` arrays
  with `segment_id` UUIDs, `status`/`terminal_outcome` = `SHIPPED`)
- `docs/examples/insights.shipped.json` — `GET /insights` (`evidence_status`, `segment_ids`,
  `quotes`, `audio_spans`)
- `docs/examples/metrics.shipped.json` — `GET /metrics`
- `docs/examples/events.shipped.json` — `GET /events`
- `docs/examples/transcript.shipped.json` — `GET /transcript`

## Processing events (GAP-BE-007)

`EventOut.stage` uses CallStatus vocabulary: `CREATED`, `UPLOADING`, `QUEUED`, `TRANSCRIBING`,
`WAITING_FOR_RECAP`, `ANALYZING`, `VALIDATING`, `INDEXING`, `BUILDING_REPORT`, terminal outcome
(`SHIPPED`/`PARTIAL`), `CANCELLED`. `state` is lowercase: `started | succeeded | failed |
retrying | skipped`. `POST /process` records a `QUEUED` event.

## SSE `GET /calls/{id}/stream` (GAP-BE-014/015)

- `event: processing` — one JSON object per processing event:
  `{ id, call_id, status, stage, state, error_code, message, created_at }`
  (`stage`/`state` use the vocabulary above; `status` is the current call status).
- `event: terminal` — `{ "status": "SHIPPED" | "PARTIAL" | "FAILED" | "CANCELLED" }`, then the
  stream closes.
- `event: error` — `{ "error": "not_found" }`.
- SSE `id:` is the event `created_at` ISO timestamp; reconnect with `Last-Event-ID` resumes.
- The stream idles out after ~30s without a terminal state; poll `/events` + `/calls/{id}` as
  fallback.
- When `AUTH_MODE=api_key`, `/stream` also accepts `?api_key=<key>` because `EventSource`
  cannot send headers. All other endpoints require the header.

## Audio playback (GAP-BE-008)

`GET /calls/{id}/audio-url` (authenticated) returns `{ "url", "expires_at" }` — a short-lived
HMAC-signed public URL usable directly as `<audio src>` (Range supported, no headers needed).
TTL is `SIGNED_URL_TTL_SECONDS` (default 900s).

## Share links (GAP-BE-006)

`POST /calls/{id}/share` returns `url` pointing at the **web app**: `{PUBLIC_WEB_BASE_URL}/shared/{token}`,
or the relative `/shared/{token}` when `PUBLIC_WEB_BASE_URL` is unset.

## Process preconditions (GAP-BE-010)

`POST /calls/{id}/process` without an uploaded audio asset (or source URL fetch) returns
**400 `INVALID_AUDIO`** (`failure_kind: USER_INPUT`). The call never enters the pipeline.

## Ask-the-Call (GAP-BE-012)

- Unindexed call → **200** `{ mode: "no_index", moments: [], evidence_segment_ids: [] }`, not 503.
- ML service down → **200** with `mode: "retrieval_lexical_fallback"` (token-overlap retrieval,
  no generation). ML outage is never presented as a deal judgment.
- Normal modes: `retrieval`, `generated`, `retrieval_generation_dropped`,
  `retrieval_generation_failed`.

## Search (GAP-BE-004)

`GET /search` (authenticated) — lexical search across insights, transcript segments, and calls.
Full architecture (FTS columns, ranking, lexical vs Ask/pgvector) is in [search.md](search.md).

**Query params:** `q` (required), `limit` (1–50, default 10), optional filters:

| Param | Applies to | Example |
|---|---|---|
| `status` | all groups (via `calls`) | `SHIPPED,PARTIAL` |
| `from` / `to` | all groups (`calls.created_at`) | `2026-01-01` |
| `call_id` | all groups | UUID |
| `speaker_role` | segments only | `customer` |
| `types` | insights only | `OBJECTION,COMPETITOR` |

**Example response:**

```json
{
  "query": "pricing",
  "groups": {
    "insights": [
      {
        "id": "<uuid>",
        "call_id": "<uuid>",
        "call_title": "Acme discovery",
        "type": "OBJECTION",
        "title": "Price pushback",
        "summary": "Customer said the plan is almost double.",
        "evidence_status": "SUPPORTED"
      }
    ],
    "segments": [
      {
        "id": "<uuid>",
        "call_id": "<uuid>",
        "text": "We currently pay about 400. This would be almost double.",
        "start_ms": 6000,
        "end_ms": 10000,
        "sequence_number": 2,
        "speaker_role": "customer"
      }
    ],
    "calls": [
      {
        "id": "<uuid>",
        "title": "Acme discovery",
        "customer_name": "Sarah",
        "status": "SHIPPED"
      }
    ]
  },
  "total": 3
}
```

## Recommendations (GAP-BE-005)

`GET /recommendations` (authenticated) → suggested explorations derived from latest-run
insights on `SHIPPED`/`PARTIAL` calls. Items appear only when their count is non-zero:

```json
{
  "available": true,
  "items": [
    {
      "id": "pricing-objections",
      "kind": "objection",
      "title": "Pricing objections",
      "description": "Calls where the customer pushed back on price.",
      "count": 2,
      "query": "pricing",
      "call_ids": ["<uuid>"]
    }
  ]
}
```

Item ids: `pricing-objections`, `objections`, `deal-risks`, `competitor-mentions`,
`commitments`. No close probability is ever derived.

## Dashboard overview

`GET /calls/overview` (authenticated) → aggregates for the workspace dashboard:

```json
{
  "total_calls": 4,
  "by_status": { "SHIPPED": 2, "CREATED": 1, "FAILED": 1 },
  "shipped": 2,
  "partial": 0,
  "failed": 1,
  "cancelled": 0,
  "processing": 1,
  "total_duration_ms": 120000,
  "insight_counts": { "OBJECTION": 3, "COMMITMENT": 4 },
  "recent_calls": [ { "id": "...", "title": "...", "status": "SHIPPED", "rep_name": null } ]
}
```

`processing` counts every non-terminal status (including `CREATED`/`UPLOADING`).
`insight_counts` uses the latest analysis run per call. `recent_calls` is the 10 newest
`CallSummary` rows.

## Call list (GAP-BE-013)

`CallSummary` now includes `rep_name`. No `biggest_risk` / badges / close probability — risk
badges stay UI-derived after report load.

## Transcript readiness (GAP-BE-011)

`GET /calls/{id}/transcript` intentionally returns an empty **200**
(`{ speakers: [], segments: [], language: null, duration_ms: null }`) before transcription.

## Worker visibility (GAP-BE-016)

`GET /health/ready` includes `workers` (count of Celery workers that answered a 1s ping) and a
`warning` when none respond, so a stuck `TRANSCRIBING` caused by a dead worker is observable.
Transcription itself is bounded by `PYAI_POLL_DEADLINE_SECONDS` and fails with
`PYAI_JOB_TIMEOUT` (infrastructure, retried with backoff, then `FAILED`).
