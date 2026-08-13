# Transcript & insight search

Lexical (full-text) search across stored call transcripts and insights. Semantic retrieval
stays on the per-call Ask path (`transcript_chunks` + pgvector); this document covers
cross-call **keyword / phrase** search only.

## Where text lives

| Store | What | When it lands |
|---|---|---|
| Postgres `transcript_segments` | Timed speaker turns (`text`, `start_ms`/`end_ms`, `speaker_id`, `sequence_number`) | End of the **transcribe** pipeline step (after PyAI normalizes) |
| Postgres `transcript_chunks` | Chunk text + `vector(1024)` embedding | Later **indexing** step (Ask-the-Call) |
| Postgres `insights` | `title` + `summary` (and typed payload) | Analysis / report build |
| SeaweedFS | Raw PyAI JSON transcript blob | Same transcribe step; **not** queried by `/search` |

A call still in `TRANSCRIBING` has **zero** segments until PyAI completes. That is expected:
there is nothing to index or search yet.

## FTS design (Postgres)

Migration `0003_transcript_search` (Postgres-only; SQLite unit tests skip DDL):

1. **`transcript_segments.text_search`** — `tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED` + GIN index `ix_transcript_segments_text_search`.
2. **`insights.text_search`** — generated over `coalesce(title,'') || ' ' || coalesce(summary,'')` + GIN `ix_insights_text_search`.
3. **`pg_trgm`** + GIN trigram index `ix_transcript_segments_text_trgm` on `transcript_segments.text` so short / substring queries (competitor names, `SOC2`) still use an index.

Existing rows backfill automatically when the STORED generated columns are added.

ORM models map `text_search` as deferred + `FetchedValue()` so SQLAlchemy never writes these
columns on insert/update.

### Query path

`GET /api/v1/search` → `app.intelligence.search.search_calls`:

- **Postgres:** `websearch_to_tsquery('english', q)` matched with `@@` against `text_search`,
  ordered by `ts_rank`. Segment queries also OR-match `ILIKE` (backed by the trigram index)
  so short tokens that yield a weak/empty tsquery still hit. If FTS returns nothing for
  insights, the handler falls back to ILIKE on title/summary.
- **SQLite (tests):** ILIKE on lowercased text only — no FTS columns required.

Calls (title / customer / rep) always use ILIKE; they are not FTS-indexed in this migration.

## Lexical vs semantic

| Capability | Mechanism | Scope |
|---|---|---|
| `/api/v1/search` | FTS / ILIKE (this doc) | Cross-call, filterable |
| `POST .../ask` | pgvector on `transcript_chunks` (+ lexical ML fallback) | Single call |

Cross-call vector search can reuse `transcript_chunks` later without further schema changes;
it is intentionally out of scope here.

## API contract

`GET /api/v1/search` (authenticated)

### Query parameters

| Param | Required | Notes |
|---|---|---|
| `q` | yes | 1–200 chars |
| `limit` | no | default 10, max 50 (per group) |
| `status` | no | Comma-separated `CallStatus` values, e.g. `SHIPPED,PARTIAL` |
| `from` / `to` | no | ISO dates; filter on `calls.created_at` (UTC day bounds) |
| `call_id` | no | Restrict all groups to one call |
| `speaker_role` | no | `seller` \| `customer` \| `unknown` — **segments only** |
| `types` | no | Comma-separated insight types, e.g. `OBJECTION,COMPETITOR` — **insights only** |

Filters combine with AND. Invalid `status` / `types` tokens return **422**.

### Response

```json
{
  "query": "SOC2",
  "groups": {
    "insights": [
      {
        "id": "<uuid>",
        "call_id": "<uuid>",
        "call_title": "Acme discovery",
        "type": "COMMITMENT",
        "title": "...",
        "summary": "...",
        "evidence_status": "SUPPORTED"
      }
    ],
    "segments": [
      {
        "id": "<uuid>",
        "call_id": "<uuid>",
        "text": "I will send the SOC2 report by Friday.",
        "start_ms": 16000,
        "end_ms": 20000,
        "sequence_number": 3,
        "speaker_role": "seller"
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

`speaker_role` / `sequence_number` support click-to-play in the UI. `call_title` on insights
avoids a second round-trip for list rendering.

## Rationale & follow-ups

- Generated `tsvector` columns keep search in sync without application write paths.
- Trigram GIN covers product jargon that stemming alone would miss.
- **Open follow-up:** cross-call semantic search over `transcript_chunks`.
- Deterministic analysis (`docs/deterministic-analysis.md`) is unchanged — search is retrieval,
  not insight generation.

## Related docs

- [ARCHITECTURE.md](ARCHITECTURE.md) §4 pipeline, §6 data model, §8 API
- [frontend-contract.md](frontend-contract.md) — wire shapes for the web client
