#!/bin/sh
# HTTPS tunnel from a reserved domain to Docker SeaweedFS S3 (seaweedfs:8333).
set -eu

if [ -z "${NGROK_AUTHTOKEN:-}" ] && [ -n "${NGROK_AUTH_TOKEN:-}" ]; then
  NGROK_AUTHTOKEN="${NGROK_AUTH_TOKEN}"
  export NGROK_AUTHTOKEN
fi

if [ -z "${NGROK_AUTHTOKEN:-}" ]; then
  echo "ngrok-seaweed skipped: NGROK_AUTHTOKEN is empty." >&2
  exec sleep infinity
fi

DOMAIN="${NGROK_SEAWEED_DOMAIN:-deal-truth-seaweed.ngrok-free.app}"
case "${DOMAIN}" in
  https://*|http://*) URL="${DOMAIN}" ;;
  *) URL="https://${DOMAIN}" ;;
esac

ADDR="${NGROK_SEAWEED_UPSTREAM:-http://seaweedfs:8333}"
echo "ngrok-seaweed ${URL} -> ${ADDR}" >&2
exec ngrok http --config=/ngrok.yml --url="${URL}" --log=stdout --log-format=json "${ADDR}"
