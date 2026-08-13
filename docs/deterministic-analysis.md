# Deterministic analysis

See formulas in `app/intelligence/metrics.py`.

- **Talk ratio** — speaking milliseconds per role divided by total speaking milliseconds.
- **Longest monologue** — longest same-speaker run with inter-segment gap ≤ 500 ms.
- **Question rate** — `?` or interrogative-prefix segments per minute of call duration.
- **Keyword / competitor hits** — case-insensitive substring match of tracked terms and aliases.
- **Silence gaps** — adjacent-segment gaps > 2000 ms.
- **Call duration** — stored `duration_ms` or last.end − first.start.

Speaker roles:

- Stereo: `stereo_seller_channel` (default 0) maps seller vs customer. Users can swap via `PATCH /speakers`.
- Mono: cue + label heuristics with confidence. Manual override always wins.
