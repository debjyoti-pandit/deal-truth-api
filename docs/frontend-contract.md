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

## Refused claims

`GET /calls/{id}/refusals` (authenticated) → what the evidence gate declined to ship, and
why. Unlike `/report`, it has **no readiness gate**: before any analysis run exists it
returns zeroed counts rather than a 409, so the UI can render the card at any point.

```json
{
  "call_id": "<uuid>",
  "refused_count": 1,
  "shipped_count": 23,
  "refusals": [
    {
      "id": "<uuid>",
      "insight_type": "CUSTOMER_FACT",
      "title": "Customer has budget approved for this quarter",
      "summary": "Customer confirmed budget.",
      "error_code": "EVIDENCE_UNSUPPORTED",
      "drop_reason": "No segment supports this claim.",
      "attempted_segment_ids": [],
      "attempted_quote": null,
      "confidence": 0.61,
      "created_at": "2026-08-14T08:45:40+00:00"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `refused_count` | Claims the validator refused on the latest analysis run. |
| `shipped_count` | Insights that run persisted. `shipped_count + refused_count` is the number of candidates the run considered — **except** in the reanalysis window described below. |
| `error_code` | Why it was refused: `EVIDENCE_UNSUPPORTED` (nothing in the transcript backs it, or the quote is not in the cited segment), `EVIDENCE_WRONG_SPEAKER` (cited the wrong speaker — e.g. a Customer Truth citing the rep), `EVIDENCE_SEGMENT_MISSING` (cited a segment that does not exist on this call). |
| `drop_reason` | One sentence, safe to show a user. |
| `attempted_segment_ids` | Segments the claim cited and failed on. **Not evidence** — never render these as proof of the claim. Empty when the claim cited nothing at all. |
| `attempted_quote` | The quote the claim asserted, when it asserted one that is not in the transcript. `null` otherwise. Render as *disputed*, never as a transcript quote. |

`refused_count` and `shipped_count` are also on the **top level of `GET /report`**, so a
Manager Brief can state both without a second request.

**The sum does not hold during reanalysis.** `PATCH /speakers` deletes the customer-only
insights and enqueues a new run, so between those two moments `shipped_count` counts a
partially-emptied run while `refused_count` still reflects the whole of it. `/report` returns
409 in that window, but `/refusals` deliberately has no readiness gate, so this is a state the
UI can render. Treat the two counts as independently true and do not assert the sum client-side.

**`refused_count` is 0 on every call today** — see `ARCHITECTURE.md` §14. The deterministic
extractors cannot produce a refusal (each filters by speaker role before emitting), so
refusals only begin once model-proposed candidates flow through the gate. Build the UI to
handle 0 gracefully; it is the current correct value, not a bug.

## Battlecard fields

`report.battlecard` is fully deterministic — fixed strings chosen by lookup, plus document
names lifted verbatim from the transcript. No model call, nothing invented.

| Field | Meaning |
|---|---|
| `documents_to_send` | Document names the rep named on the call (e.g. `"SOC2 report"`), extracted from their own words and capped at 80 chars. Empty is a legitimate answer — it means no document was named. It previously held the raw text of every seller commitment, so a full sentence could render as a "document"; it no longer does. |
| `seller_commitments` | The raw text of each seller commitment — what `documents_to_send` used to contain, under a name that describes it. |
| `top_deal_killer` | The `payload.kind` of the highest-priority deal killer, chosen by a fixed priority so the pick never depends on insight ordering. Evidenced blockers outrank absence-based ones. `null` when nothing was evidenced. |
| `primary_goal` / `questions_to_ask` | Templated from `top_deal_killer` and the qualification dimensions the transcript never supported, so two calls do not produce identical cards. Falls back to a generic three when a call evidenced nothing. Max 5 questions. |

## CRM preview — field-level provenance

`GET /calls/{id}/crm-preview` (authenticated) → what would be written to the CRM, field by
field, and what would not. Every other conversation tool writes the model's output straight
into HubSpot and inherits its hallucinations; this refuses per field, with the quote.

Like `/refusals` and unlike `/report`, there is **no readiness gate**: a call with no analysis
run answers "every gated field is blocked, nothing has been observed", which is true and
renderable, so the panel never has to disappear behind a 409.

```json
{
  "call_id": "<uuid>",
  "fields": [
    {
      "name": "call_note_why_they_buy",
      "state": "SUPPORTED",
      "value": "We're losing around 6 hours every week manually routing these calls.",
      "reason": null,
      "evidence_segment_ids": ["<uuid>"]
    },
    {
      "name": "deal_amount",
      "state": "MANUAL",
      "value": null,
      "reason": "Nothing in the transcript establishes an agreed amount. \"800 dollars\" was quoted by the rep; a figure that was said is not a figure that was agreed.",
      "evidence_segment_ids": ["<uuid>"]
    },
    {
      "name": "log_completed_meeting",
      "state": "BLOCKED",
      "value": null,
      "reason": "The customer did not commit to a next meeting.",
      "evidence_segment_ids": []
    }
  ]
}
```

Every field object always has all five keys, and every field in the table below is always
present in `fields`, in that order — a field that silently disappeared is a field nobody
notices was refused.

| Key | Meaning |
|---|---|
| `name` | The CRM property name. Stable; key your mapping on it. |
| `state` | `SUPPORTED` \| `MANUAL` \| `BLOCKED`. Only `SUPPORTED` may be written to the CRM. |
| `value` | The value to write. **Non-null only when `state` is `SUPPORTED`**; `null` for `MANUAL` and `BLOCKED`. Text values are verbatim transcript segment text — never a paraphrase, never generated. |
| `reason` | One sentence, safe to show a user, saying why the field is not written. Non-empty whenever `state` is not `SUPPORTED`; `null` when it is. |
| `evidence_segment_ids` | Segment ids from `evidence_links` → `transcript_segments`, resolvable via `GET /transcript` or `GET /insights`. **Non-empty on every `SUPPORTED` field** — that is the invariant. On `MANUAL` it shows what was found *instead* (e.g. the segment where the rep quoted a price) and is never proof of the value. On `BLOCKED` it is normally `[]`, which is the honest answer for an absence, not a missing value. |

### The three states, and how they are derived

| State | Derivation |
|---|---|
| `BLOCKED` | The dimension the field depends on is not `proven` on the latest analysis run — absent, `weak` (mentioned but below the evidence threshold), or **refused** by the evidence gate (a refused claim never becomes an insight, so it reads as absent). Derived from the same `signal_pips` the call list's `signal_pips` and the deal timeline's `dimension_states` use, so the CRM panel can never disagree with the rest of the API. |
| `MANUAL` | The gate passed (or the field has none) but no customer-attributable value could be resolved from stored transcript text. A human decides; `reason` says what was found instead. |
| `SUPPORTED` | A value was resolved out of stored segments, and those segment ids are returned with it. |

### The fields

| Field | Gate dimension | Written when | Value |
|---|---|---|---|
| `call_note_why_they_buy` | `pain_identified` | the customer described a problem | The customer's words, verbatim from the segment that established the dimension. |
| `call_note_business_impact` | `business_impact_identified` | the customer quantified the cost | Same, for the quantified-pain segment. |
| `deal_close_date` | `timeline_identified` | the customer said an actual calendar date | The date, verbatim. A relative phrase ("next week") is `MANUAL` — converting it to a date is a judgement, and this endpoint makes none. |
| `deal_amount` | *(none)* | never | Always `MANUAL`: there is no "price agreed" dimension, because a price the rep quoted is not a price the customer accepted. Any figure the call did contain is quoted verbatim in `reason` and cited in `evidence_segment_ids`. |
| `contact_is_decision_maker` | `decision_maker_identified` | the customer said who decides | `true`. |
| `contact_is_economic_buyer` | `economic_buyer_identified` | the customer said who owns the budget | `true`. |
| `log_completed_meeting` | `next_meeting_committed` | the customer committed to a next meeting | `true`. |

No score, probability, or confidence number appears anywhere in this payload — the same rule
as everywhere else in the API.

## Integrations (Slack)

`POST /integrations/slack` (authenticated) with `{"webhook_url": "https://hooks.slack.com/services/…"}`
→ `{"configured": true}`. Idempotent: posting again replaces the stored URL.

**The webhook is stored server-side and is never given back.** Do not keep a copy in
`localStorage`, a query string, or app state — the server is the only place it lives. It is
returned by no endpoint, appears in no CRM payload, and is never logged. The UI's "connected"
state comes from:

```
GET /integrations  →  { "slack": { "configured": true } }
```

Booleans only, for every provider that can be configured. There is deliberately no read-back
of the URL, no masked preview, and no "test what is stored" echo.

Validation: the URL must be `https` and its host must be `hooks.slack.com` (configurable via
`SLACK_WEBHOOK_HOSTS` for a self-hosted Slack-compatible endpoint) and it must have a path.
Anything else is **400 `WEBHOOK_URL_INVALID`** in the standard error envelope, with
`details.reason` one of `scheme` \| `host` \| `path`. The error never echoes the URL that was
sent, so a mistyped credential cannot end up in a log or a screenshot of the response.

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
- `: keepalive` — a bare SSE comment every **10s**, so a quiet stage (transcription can run
  well past a minute without emitting) is not mistaken for a dead connection by the browser
  or an intermediate proxy. Comments carry no data; `EventSource` ignores them and no
  `onmessage`/listener fires. Nothing to handle client-side — just do not treat silence
  between them as liveness.
- `event: timeout` — the stream held itself open for its full budget without the call
  reaching a terminal state, and is now closing:
  `{ call_id, status, reason: "idle_timeout", idle_seconds: 120, reconnect: true }`.
  `status` is the call's status at the moment of close (e.g. `TRANSCRIBING`) — the work is
  still in flight, this is not a failure. Reconnect to keep following it; the frame's `id:`
  is the last real event's `created_at`, so an `EventSource` reconnect resumes via
  `Last-Event-ID` instead of replaying the whole history. Falling back to polling `/events`
  + `/calls/{id}` also works.
- SSE `id:` is the event `created_at` ISO timestamp; reconnect with `Last-Event-ID` resumes.
- Budget is **120s** from stream open (was ~30s). Exactly one of `terminal`, `timeout`, or
  `error` ends any stream, so the client is never left guessing why it went quiet.
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
