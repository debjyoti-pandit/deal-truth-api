# Evidence model

Invariant: **NO PROOF IN THE TRANSCRIPT, NO CLAIM IN THE REPORT.**

Insights store `evidence_links` to `transcript_segments`. Displayed quotes are always `transcript_segments.text`. Models never generate quotes or timestamps.

Statuses:

- `SUPPORTED` — one or more real segments, speaker role valid, quote matches transcript, confidence ≥ threshold.
- `ABSENCE_BASED` — an observable gap (no timeline, no economic buyer). Not a fabricated quote.
- `UNCONFIRMED` — failed validation or low confidence. Not retried.
- `NON_FACTUAL` — courtesy language in follow-up email.

Customer Truth and sentiment points require `speaker.role == customer`.
