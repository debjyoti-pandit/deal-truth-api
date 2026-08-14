# Provider interfaces

The intelligence pipeline never depends on PyAI or S3 response shapes.

| Interface | Implementation | Notes |
|---|---|---|
| `TranscriptionProvider` | `PyAITranscriptionProvider` | Submit Hear jobs, poll or webhook, fetch authoritative result, normalize |
| `CallRecapProvider` | `PyAIRecapProvider` | `GET /recap/calls/{call_id}`; scope failures become capability warnings |
| `ComplianceProvider` | `PyAITraceProvider` | Feature-flagged; never blocks P0 |
| `MLInferenceClient` | `DealTruthMLClient` | `/v1/classify`, `/v1/emotions`, `/v1/embeddings`, `/v1/generate` on the `deal-truth-ml` Cloudflare Worker |
| `BlobStore` | `SeaweedFSS3BlobStore` | Only module that imports boto3 |

Normalized models: `NormalizedTranscript`, `NormalizedRecap`.

Webhook verification uses HMAC over the **raw request body** (`X-PyAI-Signature`). The webhook wakes the Celery worker (Redis); the job is always re-fetched. Local Compose exposes the API with ngrok so PyAI can reach the webhook and signed `audio_url`. Polling is the fallback when the tunnel is unavailable. `GET /health/ready` pings Celery (`workers` count) so a dead worker is observable, not silent.

## DealTruthMLClient details

- Base URL: `ML_SERVICE_BASE_URL`, else `https://{ML_NGROK_DOMAIN}`, else `http://localhost:8081`.
- Auth: Bearer `ML_SERVICE_API_KEY` (Worker `INTERNAL_API_TOKEN`); adds `ngrok-skip-browser-warning` for ngrok hosts.
- 300s read timeout: the Worker chunks classify/emotions internally within one HTTP request.
- Batches are id-keyed (`{"items": [{"id": "0", "text": …}]}`) with positional ids. `/v1/emotions` rejects duplicate ids with `400 INVALID_REQUEST`; responses are re-keyed by id here rather than read positionally, so a reordered response cannot hand one segment another segment's scores.
- `/v1/classify` is called **without** `candidate_labels`, so the Worker's 24-label catalogue (`GET /v1/sales-labels`) applies its own hypotheses and per-label thresholds. It returns only labels that cleared their threshold; the API's `LABEL_THRESHOLD` still gates extraction on top.
- Worker label slugs (`pain_point`) map back to extractor keys (`pain point`) via `canonical_sales_label`, which treats `-` and `_` identically (`out_of_scope_request` → `out-of-scope request`).
- Embeddings are 1024-dim, requested `normalize: true`, and land in pgvector `vector(1024)` (`transcript_chunks.embedding`).
- `generate()` posts `{"task": "summary_fallback", …}`; `MLGenerationDisabled` is raised locally when `ML_GENERATION_ENABLED=false`, before any request goes out.
- Failure modes: named `ML_*` errors; pipeline ML failures downgrade the run to `PARTIAL` with warnings; `POST .../ask` degrades to lexical retrieval. An ML outage is never a deal judgment.

### The three emotion axes

`/v1/emotions` returns `emotion`, `buying_intent` and `deal_signals` for every item, always all
three, plus an `unavailable` object. `DealTruthMLClient.emotions()` returns them as `EmotionAxes`
and never merges them — `neutral` belongs to both `emotion` and `buying_intent` and means
something different on each.

| State | Meaning |
|---|---|
| `axis: [{label, score}, …]` | Scored, these labels cleared the threshold |
| `axis: []`, `unavailable.axis == false` | Scored, nothing was confident — a genuinely flat utterance |
| `axis: []`, `unavailable.axis == true` | **Never scored. Unknown, not neutral.** |

A row missing an axis key, or a row that is not an object at all, is parsed as unavailable rather
than as an empty-but-scored axis, and a row that carries both the flag and scores has the scores
dropped so the flag can always be believed. `EmotionAxes.valence()` and `.grouped()` read the
`emotion` axis only and return `None` when it is unavailable — `None` is "we do not know", which
is not the same number as a balanced `0.0`.

All three axes are persisted verbatim on `SENTIMENT_POINT.payload` (`payload.emotion`,
`payload.buying_intent`, `payload.deal_signals`, `payload.unavailable`). `payload.grouped` is the
emotion-axis valence roll-up and is omitted entirely when that axis is unavailable. A customer
segment with every axis unavailable produces no sentiment point, so an ML gap never renders as a
finding about the customer.

`FakeMLClient(emotions={...})` accepts either the full row
(`{"emotion": {...}, "buying_intent": {...}, "deal_signals": {...}, "unavailable": {"buying_intent": true}}`)
or the older flat `{label: score}` map, which is read as the `emotion` axis with the other two
scored and empty.
