# Deal Truth API — Architecture Reference (`deal-truth-api`)

> Single source of truth for what we are building, why, and how the pieces fit together.
> Validated against the original hackathon design discussion (ChatGPT export) on 2026-08-13.

---

## 1. What We Are Building

**Deal Truth** is an open-source sales-call intelligence product. This repository
(`deal-truth-api`) is the FastAPI backend and Celery pipeline. The UI lives in
`deal-truth-web`; hosted inference lives in `deal-truth-ml` (a Cloudflare Worker over
Workers AI — the ONNX design was dropped, see §13).

A user uploads a call recording (or supplies an HTTPS recording URL). The system produces a
complete, evidence-backed call report: diarized transcript, summaries, deal insights, coaching,
follow-up email, and a queryable call memory — where **every factual claim is provably tied to
the transcript**.

### The Central Product Invariant

> **"NO PROOF IN THE TRANSCRIPT, NO CLAIM IN THE REPORT."**

- Every factual insight must reference one or more **real transcript segment IDs**.
- We **never store or display an LLM-generated quote** — displayed quotes are always loaded
  directly from stored transcript segments.
- The model may *infer*; the **evidence layer decides whether the inference ships**.
- Unsupported claims are dropped or marked `UNCONFIRMED` — never retried until they pass.
- Absence-based risks (e.g. "no timeline mentioned") are explicitly marked `ABSENCE_BASED`.

### The Demo Story

Upload call → AI produces the report → *"but summaries hallucinate"* → click any claim →
**hear the customer actually say it** → show Reality Check (rep-said vs customer-said) →
surface something the salesperson missed → show the Next Call Battlecard → generate a
follow-up email that **refuses to include unsupported commitments**.

### The Anti-Feature

We never show a fake close probability ("84% likely to close"). We show **observable deal
signal dimensions** instead: pain identified, business impact, timeline, economic buyer,
decision maker, next meeting committed, competitor active, blocker active.

---

## 2. Feature Set

### Core

| Feature | How it's built |
|---|---|
| Diarized transcript | PyAI Hear (mono diarization or stereo channel split) |
| Speaker roles and names | Heuristics + ML classification, manual override via API |
| Headline / summary / decisions / action items / next steps | PyAI Recap (normalized), ML generation fallback |
| Talk ratio, longest monologue, question rate | Deterministic Python from segment timestamps |
| Keyword and competitor mentions | Tracked terms + alias matching + zero-shot labels |

### High-Impact

| Feature | Essence |
|---|---|
| Customer Truth | Only what the **customer** actually said, categorized (pain, requirement, buying signal, blocker, budget, timeline, competition, commitment), each with exact quote + timestamps |
| Evidence receipts + click-to-play audio | Every insight carries segment IDs and `start_ms`/`end_ms`; UI seeks into original audio (no clip pre-generation) |
| Buyer emotion timeline | Three separate axes on customer segments (`emotion`, `buying_intent`, `deal_signals`) → emotion-axis valence timeline. Emotion is explicitly **not** buying intent, and the axes are never merged |
| Buying-intent signals | Observable dimensions, never a probability |
| Objections + coaching | Zero-shot detection (pricing, security, technical, budget, timing, integration, competition) + deterministic playbook responses |
| Reality Check | Rep-said vs customer-said mismatches with severity + deterministic reason codes |
| Commitment Ledger | Seller commitments / customer commitments / uncommitted next steps, with owner, action, due text, evidence |
| Deal Killers | Observable rules only (security blocker, budget blocker, active competitor, no timeline, no economic buyer, no next meeting, explicit rejection, technical blocker); statuses `SUPPORTED` / `ABSENCE_BASED` / `UNCONFIRMED` |
| Competitor intelligence | Name, mention context, customer position, evidence |
| Moments That Mattered | Normalized timestamped markers for UI timeline |
| Next Call Battlecard | Deterministic template from validated data; optional generation may polish wording but never add facts |
| Manager Brief | Pure template over existing validated insights — no model call |
| Evidence-safe follow-up email | Sentence objects `{text, evidence_segment_ids, supported}`; courtesy text marked `NON_FACTUAL`; polish must preserve sentence count + evidence mapping or fall back |
| Ask-the-Call | Qwen3 1024-dim embeddings + pgvector top-K retrieval; optional generation that must retain retrieved segment IDs; retrieval-only fallback is valid |
| Export + sharing | JSON and Markdown export; hashed, expiring, revocable read-only share tokens |

---

## 3. System Architecture

### Where Deal Truth API (`deal-truth-api`) fits in the overall product

```mermaid
flowchart TD
    Browser[User Browser] --> Caddy[Caddy reverse proxy]
    Caddy --> UI[deal-truth-web React plus Tailwind]
    UI -->|"REST + SSE"| API

    subgraph apiRepo [deal-truth-api - THIS REPO]
        API[FastAPI app] --> Valkey[(Valkey)]
        Valkey --> Worker[Celery workers]
        Worker --> Intel[Intelligence engine plus deterministic rules]
        Intel --> Validator[Evidence validator]
        Validator --> Report[Report builder and exports]
    end

    API -->|"stream audio, store uploads"| Seaweed[(SeaweedFS)]
    Worker -->|"Hear job via signed audio URL, Recap"| PyAI[PyAI Hear and Recap]
    PyAI -->|"webhook or poll"| API
    Worker -->|"v1 classify, emotions, embeddings, generate"| ML[deal-truth-ml hosted inference service]
    Worker --> PG[(Postgres plus pgvector)]
    API --> PG
```

### Repo boundaries

| Repo | Responsibility |
|---|---|
| `deal-truth-api` (**this repo**) | FastAPI backend, Celery pipeline, data model, PyAI + ML clients, evidence validation, reports, exports, sharing |
| `deal-truth-web` | React + Tailwind UI (upload, report, audio player, evidence UI) |
| `deal-truth-ml` | Cloudflare Worker + Workers AI: Qwen3 classify/emotions, Qwen3 1024-dim embeddings, GPT-OSS judge, optional generation |

### Model / responsibility split (final, post-Qwen decision)

The original design used a local Qwen3-4B LLM via llama.cpp. That was **rejected** — too slow
for a hosted demo on modest hardware. The final design uses PyAI for speech, small OSS
specialist models served by `deal-truth-ml`, and deterministic rules — a general-purpose LLM
is *not* required for most features.

| Requirement | Implementation |
|---|---|
| STT + diarization + timestamps | PyAI Hear |
| Call summary / recap | PyAI Recap (pack `sales_outbound`) |
| Emotions (three unmerged axes: `emotion`, `buying_intent`, `deal_signals`) | `@cf/qwen/qwen3-30b-a3b-fp8` fast path (via deal-truth-ml `/v1/emotions`) |
| Sales semantics (zero-shot labels) | `@cf/qwen/qwen3-30b-a3b-fp8` fast path (via deal-truth-ml `/v1/classify`); slug ids mapped back to display labels by `canonical_sales_label` |
| Embeddings | `@cf/qwen/qwen3-embedding-0.6b` → **1024-dim** → pgvector `vector(1024)` (migration `0002_embedding_1024`), via `/v1/embeddings` |
| Optional generation (polish, Ask synthesis) | Workers AI via deal-truth-ml `/v1/generate` (fast model, task `summary_fallback`; quality `@cf/openai/gpt-oss-120b` for `qa_synthesis`, not yet wired) |
| Talk ratio / monologue / questions / keywords | Deterministic Python |
| Evidence validation | Deterministic Python |
| Blob storage | SeaweedFS (S3-compatible API via boto3) |
| Database | PostgreSQL + pgvector |
| Queue / results | Valkey (Celery broker + result backend) |

**Forbidden:** OpenAI, Anthropic, Gemini, Cohere, Replicate, Hugging Face hosted inference, or
any other paid AI provider.

### Provider boundaries (architectural rule)

```mermaid
flowchart LR
    subgraph interfaces [Interfaces]
        TP[TranscriptionProvider]
        RP[CallRecapProvider]
        CP[ComplianceProvider]
        MC[MLInferenceClient]
        BS[BlobStore]
    end

    subgraph impls [Implementations]
        PT[PyAITranscriptionProvider]
        PR[PyAIRecapProvider]
        PTr[PyAITraceProvider - feature flagged]
        OM[DealTruthMLClient]
        SW[SeaweedFSS3BlobStore]
    end

    TP --- PT
    RP --- PR
    CP --- PTr
    MC --- OM
    BS --- SW
```

- **Only** `app/providers/pyai/` may know PyAI response shapes. All PyAI output is normalized
  (e.g. `NormalizedTranscript`, `NormalizedRecap`) before the intelligence pipeline sees it.
- **Only** the blob-store implementation may know boto3/S3 details.
- Trace is interface + client only, behind `PYAI_TRACE_ENABLED`; P0 never blocks on it.

---

## 4. End-to-End Pipeline

```mermaid
flowchart TD
    A[Accept call metadata] --> B[Upload or SSRF-safe fetch of source audio]
    B --> C[Store audio in SeaweedFS]
    C --> D[Submit PyAI Hear job with Idempotency-Key]
    D --> E{Ngrok webhook, else bounded polling}
    E --> F[Fetch authoritative transcription]
    F --> G[Persist raw PyAI JSON to blob store]
    G --> H[Normalize speakers and timed segments to Postgres]
    H --> I[Fetch or poll Recap when enabled]

    H --> J[Deterministic metrics]
    H --> K[Speaker role resolution]
    H --> L[ML inference - emotions, zero-shot, embeddings]

    I --> M[Derive business insights]
    J --> M
    K --> M
    L --> M

    M --> N[Evidence validation]
    N --> O[Index transcript chunks in pgvector]
    O --> P[Build report - serialized single writer]
    P --> Q[Export JSON and Markdown]
    Q --> R{Terminal outcome}
    R --> S[SHIPPED]
    R --> T[PARTIAL]
    R --> U[FAILED]
```

- The pipeline is **idempotent** end to end (stable logical idempotency keys, Celery
  `acks_late`, task idempotency). Processing an already-`SHIPPED` call is a no-op; error
  paths never overwrite a finished call.
- The stored report JSON stamps the **terminal outcome** (`SHIPPED`/`PARTIAL`), not the
  in-flight status.
- Independent analysis (metrics, emotions, labels, embeddings) fans out **in parallel** after
  transcript persistence.
- Persisted `transcript_segments` (and later `insights`) are **FTS-indexed automatically** via
  Postgres generated `tsvector` columns (migration `0003_transcript_search`); see
  [search.md](search.md).
- Anything writing final report state is **serialized** through a single finalizer task.
- Recap failure never deletes a successful transcript → the run ends `PARTIAL`, not `FAILED`.

### Call states

`CREATED → UPLOADING → QUEUED → TRANSCRIBING → WAITING_FOR_RECAP → ANALYZING → VALIDATING → INDEXING → BUILDING_REPORT → SHIPPED | PARTIAL | FAILED | CANCELLED`

Terminal outcomes: `SHIPPED`, `PARTIAL`, `FAILED`, `CANCELLED`.

Failure kinds: `INFRASTRUCTURE`, `TRANSCRIPTION`, `RECAP`, `ML_INFERENCE`, `VALIDATION`,
`STORAGE`, `DATABASE`, `USER_INPUT`.

> Infrastructure failure must **never** be represented as "the call failed a sales test."

### Retry rules

| May retry (infrastructure) | Must NOT retry (semantic) |
|---|---|
| Network timeout | Unsupported claim |
| PyAI 5xx | No evidence found |
| ML-service 5xx | Wrong speaker for claim |
| Temporary storage failure | Malformed user input |
| DB serialization failure | Absence-based risk |

Bounded exponential backoff, max attempts, a reason attached to every retry, no infinite
retries.

---

## 5. External Integrations

### PyAI (`https://api.pyai.com/v1`)

| Surface | Detail |
|---|---|
| Submit transcription | `POST /transcription/jobs` — stable Deal Truth API `call_id`, `audio_url` or multipart, `call_direction`, `customer_name`, `pack_id`, `numerals=true`, formats `json`/`srt`/`vtt`, **either** `channel=true` (stereo) **or** `diarize=true` (mono) — never both, webhook URL, `Idempotency-Key` header |
| Webhook | `POST /api/v1/webhooks/pyai/transcription` — verify `X-PyAI-Signature` HMAC over **exact raw request bytes**; webhook signals the waiting worker over Redis — always fetch the authoritative job afterwards |
| Polling fallback | Used when ngrok is down or the webhook does not arrive before the deadline. Bounded interval + named timeout (`PYAI_JOB_TIMEOUT`) |
| Local tunnel | Docker Compose `ngrok` service. `NGROK_AUTHTOKEN` required. **Stable URL:** `NGROK_DOMAIN` (Dev Domain from the ngrok dashboard) bound with `ngrok http --url`. `make up` pins `NGROK_DOMAIN` after the first tunnel if empty. Inspector `localhost:4040`. |
| Results | Handle inline `result` and offloaded `result_url`; timed segments, word timings, SRT/VTT signed URLs, mono diarization, stereo channel separation |
| Recap | `GET /recap/calls/{call_id}` (same stable call_id). Normalize status, headline, tldr, summary/summary_draft, decisions, action items, next steps, important moments, call signals, structured fields. If unavailable due to scopes: named capability warning → ML generation fallback if enabled → continue deterministic analysis → result may be `PARTIAL` |
| Audio input modes | `PYAI_AUDIO_INPUT_MODE=audio_url` (PyAI fetches a **short-lived HMAC-signed public Deal Truth API URL** — never SeaweedFS credentials) or `multipart` |

Env vars: `PYAI_API_KEY`, `PYAI_BASE_URL`, `PYAI_WEBHOOK_SECRET`, `PYAI_RECAP_ENABLED`,
`PYAI_TRACE_ENABLED`, `PYAI_RECAP_PACK_ID=sales_outbound`, `PYAI_AUDIO_INPUT_MODE`,
`PUBLIC_API_BASE_URL`, `NGROK_ENABLED`, `NGROK_API_URL`, `NGROK_AUTHTOKEN`, `NGROK_DOMAIN`.

### deal-truth-ml (hosted inference service)

**Confirmed contract** (Cloudflare Worker over Workers AI). `DealTruthMLClient` calls the
modern `/v1` routes; the compat aliases (`/classify`, `/emotion`, `/embed`, `/generate`) are
deprecated on the Worker (`Sunset: Thu, 31 Dec 2026`) and **are no longer called from here**:

```text
POST /v1/classify    {items:[{id,text}], candidate_labels?, threshold?, top_k?}
                  -> {items:[{id, labels:[{id, score, passed_threshold}]}], model, request_id}
POST /v1/emotions    {items:[{id,text}], threshold?, top_k?}
                  -> {items:[{id, emotion:[{label,score}], buying_intent:[…], deal_signals:[…],
                      unavailable:{emotion,buying_intent,deal_signals}}], model, request_id}
POST /v1/embeddings  {items:[{id,text}], normalize?} -> {items:[{id, vector, dimension, normalized}]}
POST /v1/generate    {task, input, max_new_tokens?, temperature?} -> {text, task, model, grounded:false}
```

Item ids are positional (`"0"`, `"1"`, …) and must be unique — `/v1/emotions` returns
`400 INVALID_REQUEST` on a duplicate, because scores are attributed by id and a shared id
would hand one segment another segment's emotions while still reporting `unavailable: false`.
Responses are re-keyed by that id on this side, not read positionally.

Client behavior (`app/ml/__init__.py`):

- Base URL resolution: `ML_SERVICE_BASE_URL` → `https://{ML_NGROK_DOMAIN}` → `http://localhost:8081`.
- Bearer `ML_SERVICE_API_KEY` (matches the Worker's `INTERNAL_API_TOKEN`); `ngrok-skip-browser-warning`
  header added automatically for ngrok hosts.
- 300s read timeout — the Worker chunks classify/emotions batches internally inside one HTTP request.
- `candidate_labels` is omitted, so `/v1/classify` scores against the Worker's own 24-label
  catalogue (`GET /v1/sales-labels`), which carries real NLI hypotheses and per-label thresholds
  and is a superset of `SALES_LABELS`. The route returns only labels that cleared their threshold.
- Worker label slugs (`pain_point`) are mapped back to extractor keys (`pain point`) via
  `canonical_sales_label`, which normalizes `-` and `_` alike so `out_of_scope_request` still
  resolves to `out-of-scope request`.
- Degradation: pipeline ML failures become warnings → run ends `PARTIAL` (deterministic analysis
  still ships). `POST .../ask` falls back to lexical retrieval (`retrieval_lexical_fallback`) when
  the service is down and returns `no_index` (200) when a call has no chunks. ML outage is never
  presented as a deal judgment.

Env vars: `ML_SERVICE_BASE_URL`, `ML_NGROK_DOMAIN`, `ML_SERVICE_API_KEY`, `ML_GENERATION_ENABLED`.

#### Emotion is not buying intent

Key insight from the design discussion — **a feeling is not a commercial signal**:

> "This is impressive, but there's no chance we have budget this quarter."
> Emotion: enthusiastic (positive). Commercial reality: budget blocker, low intent.

`/v1/emotions` therefore returns **three axes that are never merged and never deduped against
each other**, and every one of them is always present:

| Axis | Labels |
|---|---|
| `emotion` | `enthusiastic`, `interested`, `curious`, `neutral`, `uncertain`, `hesitant`, `concerned`, `frustrated`, `skeptical`, `rejecting` |
| `buying_intent` | `strong_positive`, `positive`, `neutral`, `weak`, `negative` |
| `deal_signals` | `pricing_blocker`, `security_blocker`, `budget_blocker`, `competitor_active`, `timeline_present`, `next_step_committed` |

`neutral` is a member of **two** axes and means something different on each, which is why the
deprecated compat `/emotion` route — which flattened all three into one `labels` array — could
not represent the canonical case at all.

**`[]` is not `unavailable`.** An empty axis means it *was* scored and nothing was confident (a
genuinely flat utterance). `unavailable.<axis> == true` means it was never scored, and the empty
array beside it is **unknown, not neutral**. Axes fail independently. All three land verbatim on
`SENTIMENT_POINT.payload` as `emotion` / `buying_intent` / `deal_signals` plus the `unavailable`
object; `payload.grouped` is an emotion-axis-only valence roll-up and is **absent** when that axis
is unavailable rather than reported as a balanced zero. A customer segment whose every axis is
unavailable produces **no** sentiment point at all — rendering that gap would turn an inference
failure into a finding about the customer.

So every customer segment gets **two parallel analyses**: the three emotion axes and commercial
signals (zero-shot classify), plus deterministic entity rules. They are stored and displayed
separately.

### SeaweedFS blob layout

Buckets: `deal-truth-audio`, `deal-truth-results`, `deal-truth-samples`.

```text
calls/{call_id}/original/{safe_filename}
calls/{call_id}/pyai/transcription.json
calls/{call_id}/pyai/recap.json
calls/{call_id}/subtitles/call.srt
calls/{call_id}/subtitles/call.vtt
calls/{call_id}/exports/report.json
calls/{call_id}/exports/report.md
```

- Streaming uploads — never read a full call into memory.
- Validation: MIME type, extension, configurable max bytes, non-empty.
- Authenticated audio streaming with **HTTP Range** support (browser seeking / click-to-play).
- Separate short-lived signed public URL: `GET /api/v1/public/audio/{asset_id}?expires=...&signature=...`
  (HMAC verify, expiry verify, streams from SeaweedFS, reveals no credentials, serves PyAI fetches).

---

## 6. Data Model

UUID primary keys unless a stable string is required. All tables via Alembic migrations.

| Table | Purpose / key fields |
|---|---|
| `calls` | public_call_id, title, customer_name, rep_name, call_direction, source_type, recording_mode (mono/stereo), status, terminal_outcome, failure_kind, duration_ms, language, timestamps, nullable `deal_id` |
| `deals` | account_name, primary_contact — groups calls into one account so a deal can be read across calls (migration `0006_deals`). Matched case-insensitively on `customer_name` at call creation; deliberately naive, correctable by a rep |
| `audio_assets` | call_id, bucket, object_key, original_filename, content_type, size_bytes, checksum |
| `speakers` | call_id, provider_speaker_id, role (seller/customer/unknown), display_name, confidence, manually_overridden |
| `transcript_segments` | call_id, provider_segment_id, speaker_id, start_ms, end_ms, text, sequence_number, metadata JSONB; Postgres `text_search` tsvector (generated) + GIN; trigram GIN on `text` |
| `analysis_runs` | call_id, version, status, model_manifest JSONB, started_at, finished_at |
| `insights` | analysis_run_id, type, title, summary, severity, confidence, evidence_status, payload JSONB; Postgres `text_search` tsvector (generated over title+summary) + GIN |
| `evidence_links` | insight_id, transcript_segment_id, relationship, sort_order |
| `refused_claims` | analysis_run_id, call_id, insight_type, title, summary, error_code, drop_reason, attempted_segment_ids JSONB, attempted_quote, confidence — claims the validator refused, recorded rather than discarded (migration `0005_refused_claims`) |
| `recap_records` | call_id, provider_status, headline, tldr, summary, raw_record JSONB |
| `call_metrics` | call_id, talk_ratio JSONB, longest_monologue JSONB, question_rate JSONB, keyword_hits JSONB |
| `transcript_chunks` | call_id, start_segment_id, end_segment_id, text, embedding vector(1024) |
| `processing_events` | call_id, stage, state, attempt, error_code, message, details JSONB |
| `share_links` | call_id, token_hash (never plaintext), expires_at, revoked_at |
| `tracked_terms` | call or org scope, type, value, aliases JSONB |

Insight types: `CUSTOMER_FACT`, `BUYING_SIGNAL`, `OBJECTION`, `COMMITMENT`, `DEAL_RISK`,
`COMPETITOR`, `REALITY_CHECK`, `CALL_MOMENT`, `COACHING`, `SENTIMENT_POINT`,
`QUALIFICATION_SIGNAL`.

Evidence references carry **segment IDs only** — models never generate timestamps; timestamps
always come from stored segments.

---

## 7. Evidence Validation (dedicated package `app/evidence/`)

Every insight passes through the validator before persistence/report:

1. Referenced segment exists.
2. Segment belongs to the same call.
3. Speaker role is valid for customer-only features (e.g. Customer Truth).
4. Timestamps come from the stored transcript.
5. Quote comes directly from transcript text.
6. No empty evidence for factual insights.
7. No duplicate insight/evidence combination.
8. Confidence threshold passed.
9. Absence-based risk explicitly marked.

Failure handling: **do not retry the model** — drop or mark `UNCONFIRMED` and log a validation
event.

A refused claim is **recorded, not discarded.** Every dropped candidate is written to
`refused_claims` with the code that refused it (`EVIDENCE_UNSUPPORTED`,
`EVIDENCE_WRONG_SPEAKER`, `EVIDENCE_SEGMENT_MISSING`), a human-readable reason, and the
segments and quote it tried and failed to stand on. This is what makes the gate
demonstrable: without it the API can report what it said, never what it declined to say.
The attempted segments are stored as plain JSON, deliberately **not** as `evidence_links` —
those segments do not support the claim and must never be joined as though they did.

Note that the deterministic extractors cannot themselves produce a refusal: each filters by
speaker role before emitting and cites only segments it just read. Refusals arise from
**model-proposed** candidates, so `refused_count` stays 0 until `/v1/analyze-call` is adopted
(see §14).

---

## 8. API Surface

| Group | Endpoints |
|---|---|
| Health | `GET /health/live`, `GET /health/ready` (readiness includes `workers` — Celery ping count — outside test env) |
| Calls | `POST /api/v1/calls`, `GET /api/v1/calls` (summaries include `rep_name`), `GET /api/v1/calls/{call_id}`, `DELETE /api/v1/calls/{call_id}` |
| Dashboard | `GET /api/v1/calls/overview` — status counts, latest-run insight counts, `recent_calls` (registered **before** `/calls/{call_id}` so the literal path wins) |
| Deals | `GET /api/v1/deals/{deal_id}` — `{account_name, primary_contact, call_count, span_days, calls[], deltas[]}`. Each call carries `dimension_states` (the 8 observable dimensions); `deltas` is a pure Python diff of consecutive states, surfacing a dimension that was `proven` on the previous call and has since gone. **No health score** — counting proven dimensions is observable, a 0–100 number is not |
| Audio | `POST .../audio` (upload), `POST .../source-url` (SSRF-safe fetch), `GET .../audio` (Range streaming), `GET .../audio-url` (mints `{url, expires_at}` for `<audio src>`), `GET /api/v1/public/audio/{asset_id}` (signed) |
| Processing | `POST .../process` (**400 `INVALID_AUDIO`** without an audio asset; logs a `QUEUED` event), `POST .../reanalyze`, `POST .../cancel`, `GET .../events`, `GET .../stream` (SSE) |
| Transcript | `GET .../transcript` (empty 200 before transcription), `PATCH .../speakers` (role swap → invalidate customer-only insights → enqueue reanalysis, preserve transcript) |
| Report | `GET .../report`, `GET .../insights`, `GET .../metrics`, `GET .../refusals` — report/exports return **409 `NOT_READY`** until `SHIPPED`/`PARTIAL`; `/refusals` has no readiness gate and returns zeroed counts before analysis |
| Ask | `POST .../ask` — `no_index` (200) when unindexed; lexical fallback when ML is down |
| Search | `GET /api/v1/search?q=` — ranked Postgres FTS (`websearch_to_tsquery` + `ts_rank`) with filters `status`, `from`/`to`, `call_id`, `speaker_role`, `types`; SQLite ILIKE in tests. See [search.md](search.md) |
| Recommendations | `GET /api/v1/recommendations` — suggested explorations from latest-run insights on finished calls |
| Follow-up | `POST .../follow-up` |
| Sharing | `POST .../share` (URL uses `PUBLIC_WEB_BASE_URL`), `DELETE .../share/{share_id}`, `GET /api/v1/shared/{token}` → `{ report, transcript }` |
| Export | `GET .../export/json`, `GET .../export/markdown` |
| Webhooks | `POST /api/v1/webhooks/pyai/transcription` |
| Reference docs | `GET /api/v1/reference`, `GET /api/v1/reference/{name}` — allowlisted markdown from `docs/` |

SSE supports event IDs, `Last-Event-ID`, reconnect, and a terminal event. Because
`EventSource` cannot send headers, `/stream` also accepts `?api_key=` when
`AUTH_MODE=api_key` (query auth is scoped to `/stream` only). Event `stage` values use
CallStatus vocabulary and `state` is lowercase — full wire contract, SSE payload shape,
and committed sample payloads (`docs/examples/*.shipped.json`) are in
[frontend-contract.md](frontend-contract.md).

### Named errors (consistent API error envelope)

- **PyAI:** `PYAI_AUTH_FAILED`, `PYAI_PAYMENT_REQUIRED`, `PYAI_SCOPE_MISSING`, `PYAI_SUBMIT_FAILED`, `PYAI_WEBHOOK_SIGNATURE_INVALID`, `PYAI_JOB_FAILED`, `PYAI_JOB_CANCELLED`, `PYAI_JOB_TIMEOUT`, `PYAI_RESULT_FETCH_FAILED`, `PYAI_RECAP_PENDING_TIMEOUT`, `PYAI_RECAP_FAILED`
- **ML:** `ML_SERVICE_UNAVAILABLE`, `ML_AUTH_FAILED`, `ML_MODEL_NOT_READY`, `ML_INFERENCE_FAILED`, `ML_GENERATION_DISABLED`, `ML_RESPONSE_INVALID`
- **Storage:** `BLOB_UPLOAD_FAILED`, `BLOB_DOWNLOAD_FAILED`, `BLOB_NOT_FOUND`, `INVALID_AUDIO`, `AUDIO_TOO_LARGE`
- **Analysis:** `SPEAKER_ROLE_UNRESOLVED`, `EVIDENCE_SEGMENT_MISSING`, `EVIDENCE_WRONG_SPEAKER`, `EVIDENCE_UNSUPPORTED`, `ANALYSIS_SCHEMA_INVALID`, `EMBEDDING_FAILED`
- **Database:** `DATABASE_WRITE_FAILED`, `MIGRATION_REQUIRED`
- **Request:** `NOT_FOUND`, `CONFLICT`, `NOT_READY` (409, retryable — report/exports/shared before `SHIPPED`/`PARTIAL`), `UNAUTHORIZED`, `FORBIDDEN`, `INVALID_SOURCE_URL`, `SHARE_TOKEN_INVALID`, `SIGNED_URL_INVALID`, `CALL_CANCELLED`

---

## 9. Security

- `AUTH_MODE=none` or `AUTH_MODE=api_key` (no full identity system for P0).
- No PyAI key or storage credentials in any frontend response.
- CORS configurable.
- HTTPS-only source URL fetching with **SSRF protection**: reject localhost, private ranges,
  link-local addresses; re-check after redirects.
- Safe filenames, upload size limits.
- Share tokens stored **hashed**, expiring, revocable.
- Signed audio URLs expire.
- Logs must not contain full transcripts or credentials (redaction built into logging).

---

## 10. Deterministic Metrics (no generative models)

Computed purely from segment timestamps and text; exact formulas documented in
`docs/deterministic-analysis.md` when implemented:

talk ratio, speaking duration per speaker, longest uninterrupted monologue, question count and
questions per speaker, keyword hits, tracked competitor hits, silence gaps (where timings
permit), call duration.

---

## 11. Tech Stack Summary

```text
BACKEND    Python 3.12, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2, Alembic
ASYNC      Celery + Valkey (broker + result backend)
DATA       PostgreSQL + pgvector (asyncpg), embeddings vector(1024)
BLOB       SeaweedFS via S3 API (boto3)
SPEECH     PyAI Hear + Recap (Trace feature-flagged)
ML         deal-truth-ml Cloudflare Worker (Workers AI: Qwen3 fast, GPT-OSS-120B quality,
           Qwen3-Embedding-0.6B 1024-dim, BGE rerank)
HTTP       httpx
TOOLING    uv, Ruff, MyPy, pytest + pytest-asyncio
DEPLOY     Docker + docker-compose (postgres, redis, seaweedfs, api, worker, ngrok)
LICENSE    MIT
```

---

## 12. Testing & Fixtures

No customer audio or transcripts ever committed. Ten synthetic fixture scenarios:

1. Happy path
2. Pricing objection
3. Security blocker
4. Active competitor
5. Positive emotion but no budget
6. No purchase timeline
7. No economic buyer
8. Seller overstates buyer intent
9. Seller commitment with due date
10. Customer changes/weakens commitment

Plus PyAI response fixtures, Recap fixtures, ML-service fixtures, expected-report fixtures.

Test layout: `tests/{unit,integration,contract,live}`. Live PyAI tests gated by
`RUN_PYAI_LIVE_TESTS=1` (never in normal CI). CI runs Ruff, MyPy, pytest, Alembic migration
check, Docker build.

Acceptance criteria: API + worker start, migrations apply, fixture pipeline reaches
`SHIPPED`, `PARTIAL` and `FAILED` paths tested, valid OpenAPI schema, Docker image builds, all
core endpoints exist, evidence validator blocks unsupported claims, no secrets/customer data
committed, README covers startup + live tests.

---

## 13. Design Decisions Log

| Decision | Rationale |
|---|---|
| Dropped local Qwen3-4B + llama.cpp | Too slow for hosted demo on modest hardware; specialist models + rules cover most features |
| Specialist models over general LLM | Extraction is classification, not generation; deterministic + auditable |
| PyAI Recap added on top of the original design | Managed summary surface; failure degrades to `PARTIAL`, never destroys transcript |
| Emotions ≠ intent, stored separately | "Impressive, but no budget" is positive emotion + negative deal signal |
| No close probability | Fake precision; observable dimensions instead |
| Seek-to-timestamp audio evidence | No clip pre-generation; original recording + Range requests |
| Webhook is trigger-only | Authoritative result always fetched from PyAI after signature verification |
| Retry only infrastructure failures | Retrying a semantic failure until it "happens to pass" fabricates evidence |
| React UI / Caddy out of this repo | Lives in `deal-truth-web`; `deal-truth-api` is API + pipeline only |
| ML models out of this repo | Live in `deal-truth-ml`; Deal Truth API only consumes its HTTP contract |

## 14. Known Open Items

- `refused_count` is 0 on every call today. The evidence gate and `refused_claims` are wired
  end to end, but only **model-proposed** candidates can fail validation, and the API still
  builds candidates deterministically. Adopting `/v1/analyze-call` is what starts populating
  it — until then the refusal machinery is proven by unit tests, not by live data.
- ~~Confirm the hosted `deal-truth-ml` endpoint contract~~ — **confirmed**, and ~~migrate off the
  compat aliases~~ — **done**: the client speaks `/v1/classify`, `/v1/emotions`, `/v1/embeddings`
  and `/v1/generate` (see §5). Any future drift stays isolated to `DealTruthMLClient`.
- `/v1/rerank` (BGE reranker, would materially improve Ask) and `/v1/analyze-call` are both built
  on the Worker and still unused here.
- `/v1/generate` is called with the `summary_fallback` task only. Ask synthesis still uses the
  same task rather than `qa_synthesis`, so it runs on the fast model.
- `deal-truth-ml` availability is operational (Cloudflare Workers AI quota / ngrok tunnel);
  the API degrades to `PARTIAL` + lexical Ask when it is down.
- PyAI Speak for generating synthetic sample calls (mentioned in original design) is optional and not part of P0; `deal-truth-samples` bucket exists for it.
- PyAI Trace remains interface-only behind `PYAI_TRACE_ENABLED`.

## 15. Frontend contract

The web UI (`deal-truth-web`) integration contract — NOT_READY semantics, event/SSE wire
shapes, `audio-url` minting, share URLs (`PUBLIC_WEB_BASE_URL`), search, recommendations,
dashboard overview, Ask degradation modes — lives in
[frontend-contract.md](frontend-contract.md), with committed sample payloads under
[examples/](examples/) (regenerate: `uv run python scripts/generate_report_examples.py`).
Both are served live at `/api/v1/reference`.

> The committed `examples/*.json` still show the pre-`/v1` `SENTIMENT_POINT` payload
> (`grouped` with a synthesized `neutral`, plus a flattened `raw` map). Re-run the generator
> to refresh them against the three-axis payload.
