# Security Policy

## Reporting

Email security issues privately. Do not open a public GitHub issue for credential leaks or exploitable bugs.

## Secrets

- Store credentials in environment variables or a secret manager.
- `.env.example` contains empty placeholders only.
- Never log API keys, storage credentials, ngrok tokens, signatures, or full transcripts.
- Share tokens are stored as SHA-256 hashes. Signed audio URLs expire.
- Ngrok exposes the local API to PyAI. Treat `NGROK_AUTHTOKEN` as a secret; do not commit it.

## Authentication

P0 supports `AUTH_MODE=none` (local/dev) and `AUTH_MODE=api_key`. This is not a full identity system. Do not expose an `AUTH_MODE=none` deployment on the public internet.

## Source URLs

The API fetches remote recordings over HTTPS only and rejects localhost, private, link-local, and reserved addresses (including after redirects).

## Supported versions

Security fixes apply to the latest `main` branch.
