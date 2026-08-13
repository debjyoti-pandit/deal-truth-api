# Provider interfaces

The intelligence pipeline never depends on PyAI or S3 response shapes.

| Interface | Implementation | Notes |
|---|---|---|
| `TranscriptionProvider` | `PyAITranscriptionProvider` | Submit Hear jobs, poll or webhook, fetch authoritative result, normalize |
| `CallRecapProvider` | `PyAIRecapProvider` | `GET /recap/calls/{call_id}`; scope failures become capability warnings |
| `ComplianceProvider` | `PyAITraceProvider` | Feature-flagged; never blocks P0 |
| `MLInferenceClient` | `DealTruthMLClient` | `/classify`, `/emotion`, `/embed`, `/generate` |
| `BlobStore` | `SeaweedFSS3BlobStore` | Only module that imports boto3 |

Normalized models: `NormalizedTranscript`, `NormalizedRecap`.

Webhook verification uses HMAC over the **raw request body** (`X-PyAI-Signature`). The webhook wakes the Celery worker (Redis); the job is always re-fetched. Local Compose exposes the API with ngrok so PyAI can reach the webhook and signed `audio_url`. Polling is the fallback when the tunnel is unavailable.
