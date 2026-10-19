#!/usr/bin/env bash
# Gated deploy: runs `make gate`, then `railway up`, then smoke-checks the public URL.
# Needs a Railway project token in RAILWAY_TOKEN (or RAILWAY_API_TOKEN) and PUBLIC_URL.
set -euo pipefail

if [ -z "${RAILWAY_TOKEN:-}" ] && [ -n "${RAILWAY_API_TOKEN:-}" ]; then
  # The CLI rejects a project token under RAILWAY_API_TOKEN.
  export RAILWAY_TOKEN="$RAILWAY_API_TOKEN"
fi
unset RAILWAY_API_TOKEN
: "${RAILWAY_TOKEN:?RAILWAY_TOKEN is required}"
: "${PUBLIC_URL:?PUBLIC_URL is required (https://<domain>)}"

make gate
railway up --ci --service meridian --environment production

check() { # name, expected status, curl args...
  local name=$1 want=$2 got
  shift 2
  got=$(curl -sS -o /dev/null -w '%{http_code}' "$@")
  [ "$got" = "$want" ] || { echo "FAIL $name: got $got, want $want" >&2; exit 1; }
  echo "ok   $name ($got)"
}

body() { curl -sS "$@"; }

body "$PUBLIC_URL/" | grep -q 'Meridian Home Comfort'
check "GET /" 200 "$PUBLIC_URL/"
body "$PUBLIC_URL/business" | grep -q 'Meridian AI agent: business view'
check "GET /business" 200 "$PUBLIC_URL/business"
check "GET /health" 200 "$PUBLIC_URL/health"
check "POST /conversations" 201 -X POST "$PUBLIC_URL/conversations"
id=$(body -X POST "$PUBLIC_URL/conversations" | python3 -c 'import json,sys; print(json.load(sys.stdin)["conversationId"])')
check "POST messages" 200 -X POST -H 'Content-Type: application/json' -d '{"text":"hello"}' "$PUBLIC_URL/conversations/$id/messages"
body -X POST -H 'Content-Type: application/json' -d '{"text":"hi"}' "$PUBLIC_URL/conversations/not-a-real-id/messages" | grep -q conversation_not_found
check "POST unknown conversation" 404 -X POST -H 'Content-Type: application/json' -d '{"text":"hi"}' "$PUBLIC_URL/conversations/not-a-real-id/messages"
