# Evidence model

Invariant: **NO PROOF IN THE TRANSCRIPT, NO CLAIM IN THE REPORT.**

Insights store `evidence_links` to `transcript_segments`. Displayed quotes are always `transcript_segments.text`. Models never generate quotes or timestamps.

Statuses:

- `SUPPORTED` — one or more real segments, speaker role valid, quote matches transcript, confidence ≥ threshold.
- `ABSENCE_BASED` — an observable gap (no timeline, no economic buyer). Not a fabricated quote.
- `UNCONFIRMED` — failed validation or low confidence. Not retried.
- `NON_FACTUAL` — courtesy language in follow-up email.

Customer Truth and sentiment points require `speaker.role == customer`.

## Refused claims

A claim that fails validation is **recorded, not discarded**. Each one is written to
`refused_claims` with its `error_code` (`EVIDENCE_UNSUPPORTED`, `EVIDENCE_WRONG_SPEAKER`,
`EVIDENCE_SEGMENT_MISSING`), a `drop_reason`, and the `attempted_segment_ids` /
`attempted_quote` it failed to stand on. Read them at `GET /api/v1/calls/{id}/refusals`.

A refusal is the gate working. It is never retried — retrying a semantic failure until it
happens to pass is how evidence gets fabricated.

The attempted segments are stored as JSON, never as `evidence_links`: they do not support
the claim, and nothing may join them as if they did.
