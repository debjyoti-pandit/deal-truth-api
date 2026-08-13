# Named errors

Every API error uses:

```json
{
  "error": {
    "code": "PYAI_JOB_TIMEOUT",
    "message": "human readable",
    "details": {},
    "retryable": true,
    "failure_kind": "INFRASTRUCTURE"
  }
}
```

## PyAI

`PYAI_AUTH_FAILED`, `PYAI_PAYMENT_REQUIRED`, `PYAI_SCOPE_MISSING`, `PYAI_SUBMIT_FAILED`, `PYAI_WEBHOOK_SIGNATURE_INVALID`, `PYAI_JOB_FAILED`, `PYAI_JOB_CANCELLED`, `PYAI_JOB_TIMEOUT`, `PYAI_RESULT_FETCH_FAILED`, `PYAI_RECAP_PENDING_TIMEOUT`, `PYAI_RECAP_FAILED`

## ML

`ML_SERVICE_UNAVAILABLE`, `ML_AUTH_FAILED`, `ML_MODEL_NOT_READY`, `ML_INFERENCE_FAILED`, `ML_GENERATION_DISABLED`, `ML_RESPONSE_INVALID`

## Storage

`BLOB_UPLOAD_FAILED`, `BLOB_DOWNLOAD_FAILED`, `BLOB_NOT_FOUND`, `INVALID_AUDIO`, `AUDIO_TOO_LARGE`

## Analysis

`SPEAKER_ROLE_UNRESOLVED`, `EVIDENCE_SEGMENT_MISSING`, `EVIDENCE_WRONG_SPEAKER`, `EVIDENCE_UNSUPPORTED`, `ANALYSIS_SCHEMA_INVALID`, `EMBEDDING_FAILED`

## Database

`DATABASE_WRITE_FAILED`, `MIGRATION_REQUIRED`

## Request / general

`NOT_FOUND` (404), `CONFLICT` (409), `NOT_READY` (409, retryable), `UNAUTHORIZED` (401),
`FORBIDDEN` (403), `INVALID_SOURCE_URL` (400), `SHARE_TOKEN_INVALID` (404),
`SIGNED_URL_INVALID` (403), `CALL_CANCELLED` (409)

`NOT_READY` is returned by `GET .../report`, `GET .../export/json|markdown`, and
`GET /shared/{token}` until the call reaches `SHIPPED` or `PARTIAL`. Clients should poll or
watch processing events; these endpoints never return a bare 500 for an unready call.

Infrastructure failures may retry. Semantic failures (no evidence, wrong speaker, malformed input) must not retry.
