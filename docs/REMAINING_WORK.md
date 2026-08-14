# Remaining work — `deal-truth-api` + `deal-truth-ml`

> State as of 2026-08-14, after the 17-task queue (ML-1…7, API-1…10) and the 1-hour-call fix
> landed. This file is the queue for the next session: what is still open in each repo, why it
> matters, and where the code is. Mirrored in both repos, like `BACKEND_CHANGES.md`.
>
> The product invariant governs everything below: **no proof in the transcript, no claim in
> the report.** Nothing on this list is licensed to add a score, a probability, or a
> denormalised quote.

---

## `deal-truth-api`

### 1. Wire `/v1/analyze-call` — this is what makes `refused_count` real

`GET /calls/{id}/refusals`, the `refused_claims` table, and the report's
`refused_count`/`shipped_count` are all live — and **`refused_count` is 0 on every real call**,
because the deterministic extractors (`app/intelligence/extract.py`) filter by speaker role
before emitting and structurally cannot produce a refusable candidate. Only model-proposed
candidates can fail the gate. `/v1/analyze-call` (two-stage: Qwen candidates → GPT-OSS judge)
is built, documented and unused.

Do: call it from the pipeline, map its judged insights into `CandidateInsight`s (segment ids
only — it already returns nothing else), and let `validate_candidates` decide what ships. Then
run the deferred API-1 validation for real:

```bash
curl -s localhost:8000/api/v1/calls/$CALL_ID/refusals | \
  jq -e '.refused_count > 0 and (.refusals | all(has("error_code") and has("drop_reason")))' && echo PASS
```

Touches: `app/pipeline/runner.py`, `app/ml/__init__.py` (new client method),
`app/providers/fakes.py`, `docs/ARCHITECTURE.md` §5/§14.

### 2. Wire `/v1/rerank` into Ask, and Ask synthesis onto the quality model

Ask currently returns raw vector hits; the first moment is what gets played on stage.
`/v1/rerank`'s contract is pinned and tested (ranked desc, stable ties, empty → 200):
retrieval top-15 → rerank top-5. Separately, Ask generation goes through `generate` with task
`summary_fallback` (fast model); `qa_synthesis` (GPT-OSS-120B) is the documented route for it.

Touches: `app/intelligence/ask.py`, `app/ml/__init__.py`, `app/api/v1/report.py`.

### 3. Speaker-role inversion bug (degrades the best demo moment)

`_mono` in `app/intelligence/speakers.py` scores speakers with **empty `label_scores`**, so the
outbound-first-speaker `+0.5` decides alone. On the `customer_weakens_commitment` fixture the
roles invert: *"Actually, just send me something and I'll get back to you."* is attributed to
the **seller**, so the follow-up's contradiction pointer resolves to a weaker line than the one
the demo wants. Fix the scoring to actually use the classifier scores; add a fixture test
asserting that line lands on the customer.

### 4. Emotions recall: Qwen silently drops ~half the items in a batch

Live 8-item batch, 5/5 trials: items 5–7 came back with every axis `unavailable` (that flag is
what made this visible — before ML-1 they read as "neutral"). *"Finance froze the budget until
next year"* was among the dropped. Options, in rough order: shrink `EMOTION_ITEM_CHUNK` (4 → 2)
on the Worker; one re-ask pass for dropped items only; surface per-call unavailable counts as a
report warning so the gap is at least visible in the product. Cross-repo with ML §3 below.

### 5. Per-chunk degradation for the batched client (enhancement)

The 1-hour fix chunks classify/emotions/embeddings to `ML_MAX_BATCH_SIZE` per request,
all-or-nothing: any chunk failing raises, pipeline → `PARTIAL` (identical blast radius to the
old single request). Two follow-ups worth considering, neither urgent:

- **Emotions**: a failed chunk could synthesize all-axes-`unavailable` for its items instead of
  failing the call — the vocabulary for that already exists and the Worker itself degrades
  per-chunk this way. Never for embeddings: `persist_chunks` zips chunks to vectors and a
  partial list risks misalignment (`strict=False` truncates silently — worth making `strict=True`
  while in there).
- **Bounded concurrency** (e.g. 4 in-flight): a 700-segment call is ~22 sequential requests per
  ML op today. Works, just slow; `httpx.Client` is thread-safe.

### 6. UI coordination — response shapes that changed this session

The parity suite (`deal-truth-ui`: `VITE_API_BASE_URL=http://localhost:8000 npm run parity`)
has **not** been run against the live API. Shapes the UI must absorb:

| Change | Where |
|---|---|
| `battlecard.documents_to_send` = document names; raw text moved to new `seller_commitments`; new `top_deal_killer` | `frontend-contract.md` §Battlecard |
| `SENTIMENT_POINT.payload` = three axes + `unavailable`; flat `raw` map gone; `grouped` emotion-only and omitted when unavailable | `frontend-contract.md`, examples |
| `CallSummary` gains `signal_pips`, `top_risk`, `deal_id` | API-2 |
| Report insights carry `id` (nullable when unmatched); top-level `shipped_count`/`refused_count` | API-4 / API-1 |
| New endpoints: `/refusals`, `/deals/{id}`, `/crm-preview`, `/integrations{,/slack}` | contract doc |
| SSE: `: keepalive` every 10s, `event: timeout`, 120s budget | contract doc §SSE |

### 7. Slack alert *sending*

Storage (API-10) and formatting (`/v1/notify/preview`, ML-7) both exist; nothing sends. Build
the dispatcher: on pipeline finish, POST rendered blocks for **claim refused** and **dimension
lost** (from `deals` deltas) to the stored webhook. The webhook must never appear in logs or
responses (containment already enforced; keep it that way).

### 8. Operational / smaller items

- **`make smoke` against the full Docker stack** and the end-to-end chain check
  (`PROMPT_ML.md` final gate) have not been run this session — only `make check` (in-process,
  40/40) and targeted live Worker checks.
- **1-hour-call envelope, verified vs assumed**: ML batching fixed + live-proven;
  `PYAI_POLL_DEADLINE_SECONDS` default raised 600 → 1800 (Celery `visibility_timeout` follows
  it) — but **no real 1-hour recording has been run end to end**. Do one before the demo.
- `docs/openapi.json`: `scripts/export_openapi.py` writes it but it has never been tracked;
  decide whether to commit it.
- Pagination on `GET /calls`; tracked-term CRUD (`organization_scope` exists, no API);
  `AnalysisRun` history endpoint; `EvidenceLink.relationship="contradicts"` modelled, unused;
  `InsightType.BUYING_SIGNAL` declared, never emitted — wire or remove;
  `recommendations.available` always `true`. (Post-hackathon list, `BACKEND_CHANGES.md` §12.)
- `refused_claims` has no ORM relationship from its parents (DB `ON DELETE CASCADE` only —
  correct on Postgres, orphans on SQLite in tests). Cosmetic.
- Husky v9 deprecation warnings on every commit in both repos (two lines to delete per hook).
- Celery `visibility_timeout` is `PYAI_POLL_DEADLINE_SECONDS + 120` and does not budget the
  ML phase (worst case N×300s on a very long call). Mitigated today by the idempotent,
  acks-late task — a redelivered run is a no-op — but worth a real budget when touching
  `app/tasks/celery_app.py`.

---

## `deal-truth-ml`

### 1. Delete the compat routes (now unblocked)

`/classify`, `/emotion`, `/embed`, `/generate` carry `Deprecation: true` + `Sunset:
2026-12-31` and **nothing calls them anymore** (API-7 moved the client to `/v1`). Deletion is
now safe after a short soak: remove the handlers, their entries in `PROTECTED_PREFIXES`, the
compat tests, and the compat sections of `docs/API.md`/`src/openapi.ts`/`README.md`.

### 2. Add a `business_impact` label (coordinate with the API)

`business_impact_identified` is the weakest-supported dimension: the 24 labels contain no
impact label, so `DIMENSION_MAP` leans on `customer_concern`. The real fix is a 25th label —
which requires updating the 24-count assertion in `test/unit/core.test.ts`, `DIMENSION_MAP`,
`docs/MODELS.md`, and API-side `SALES_LABELS`/`canonical_sales_label`/`_quantified_pain`.
Related decision, currently deliberate: `customer_commitment`/`seller_commitment` map to
`null`, not `next_meeting_committed` — a commitment to send a deck is not a booked meeting. If
product wants "any committed next step", it is a one-line change plus a MODELS.md row.

### 3. Emotions item-drop mitigation (Worker side of API §4)

At temperature 0, Qwen reliably answers only part of the second chunk of a batch. Candidates:
`EMOTION_ITEM_CHUNK` 4 → 2; a single re-ask for items missing from the response (bounded, once
— re-asking until they pass would fabricate); or accept and let the API surface the gap.
Measure neuron cost before choosing.

### 4. Error-code follow-ups

- Promote `LLM_SCHEMA_MISMATCH` from `SCHEMA_INVALID` + `details.reason` to a first-class
  `ErrorCode` (4 lines in `src/core/errors.ts` + one argument in `generate.ts`).
- Switch the emitted `UPSTREAM_AI_ERROR` → `UPSTREAM_FAILED`. Already safe: the Python client
  maps by **status code**, not code string. Update `emotions-axes.test.ts:133` and the docs
  table in the same commit.

### 5. Live-model verification not yet run

`RUN_MODEL_TESTS=1 npm run test:live` ran for emotions/classify/embeddings during ML-1, but:
the rerank behavioural check (pleasantry ranks last on the **real** BGE model), the generation
guard against **real** Qwen leakage, and the timeout classifier against a real Workers AI
stall are all verified only against fakes. Run the live suite before the demo; it burns
neurons.

- `score_placeholder` guard trade-off, known and accepted: a legitimate generation containing
  "NPS score: 8" is rejected (fail-closed → named error → caller falls back). Revisit only if
  it fires in practice.

### 6. Housekeeping

- `docs/PROMPT_ML.md`, `docs/BACKEND_CHANGES.md`, `docs/RUNNER_BACKEND.md` are untracked and
  not prettier-clean, so `npm run format` rewrites them and `format:check` warns. Either commit
  them formatted or add them to `.prettierignore`.
- `wrangler deploy` + `INTERNAL_API_TOKEN` secret for production; the API's
  `ML_SERVICE_API_KEY` must match.

---

## Cross-repo, in order

1. API §1 (analyze-call) → refusals become real → API §7 (alerts) has something to send.
2. API §2 (rerank + qa_synthesis) — pure adoption, ML side is done.
3. ML §1 (delete compat) after a soak of API-7 in real use.
4. ML §2 (business_impact label) — one coordinated change, both repos, same day.
5. The full-stack gates nothing has run end to end: `make smoke` (API, Docker up),
   `RUN_MODEL_TESTS=1 npm run test:live` (ML), the UI parity suite, and one real 1-hour
   recording through the whole chain:

```bash
curl -s localhost:8000/api/v1/calls/$CALL_ID/report | jq -e '
  .sentiment_timeline | all(
    (.payload.emotion|type=="array") and
    (.payload.buying_intent|type=="array") and
    (.payload.deal_signals|type=="array"))' && echo "END-TO-END READY"
```
