#!/bin/sh
# Start an ngrok HTTPS tunnel to the OpenGong API (host port 8000).
# Always bind a stable hostname when NGROK_DOMAIN is set (ngrok --url).
set -eu

# Official ngrok env is NGROK_AUTHTOKEN; also accept NGROK_AUTH_TOKEN.
if [ -z "${NGROK_AUTHTOKEN:-}" ] && [ -n "${NGROK_AUTH_TOKEN:-}" ]; then
  NGROK_AUTHTOKEN="${NGROK_AUTH_TOKEN}"
  export NGROK_AUTHTOKEN
fi

if [ -z "${NGROK_AUTHTOKEN:-}" ]; then
  echo "ngrok skipped: NGROK_AUTHTOKEN / NGROK_AUTH_TOKEN is empty." >&2
  echo "Add a token from https://dashboard.ngrok.com/get-started/your-authtoken to .env" >&2
  echo "Without it, PyAI cannot POST webhooks or fetch signed audio_url (localhost is not reachable)." >&2
  exec sleep infinity
fi

ADDR="${NGROK_UPSTREAM:-http://host.docker.internal:8000}"

DOMAIN="${NGROK_DOMAIN:-}"
case "${DOMAIN}" in
  https://*|http://*) URL="${DOMAIN}" ;;
  "") URL="" ;;
  *) URL="https://${DOMAIN}" ;;
esac

if [ -n "${URL}" ]; then
  echo "ngrok using stable domain ${URL}" >&2
  exec ngrok http --config=/ngrok.yml --url="${URL}" --log=stdout --log-format=json "${ADDR}"
fi

echo "ngrok NGROK_DOMAIN is empty; starting without a pinned URL." >&2
echo "After the first tunnel, make up writes NGROK_DOMAIN so later restarts stay stable." >&2
echo "Or set NGROK_DOMAIN to your Dev Domain from https://dashboard.ngrok.com/domains" >&2
exec ngrok http --config=/ngrok.yml --log=stdout --log-format=json "${ADDR}"
