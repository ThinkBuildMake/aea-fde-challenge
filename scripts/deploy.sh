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

if [ -n "$(git status --porcelain --untracked-files=all)" ]; then
  echo "Refusing to deploy a dirty working tree (tracked changes or untracked files)." >&2
  exit 1
fi

make gate
railway up --ci --service meridian --environment production

# `railway up --ci` may return before the new deployment answers: poll /health.
for _ in $(seq 1 60); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "$PUBLIC_URL/health" || true)" = "200" ]; then
    break
  fi
  sleep 5
done

check() { # name, expected status, curl args...
  local name=$1 want=$2 got
  shift 2
  got=$(curl -sS -o /dev/null -w '%{http_code}' "$@")
  [ "$got" = "$want" ] || { echo "FAIL $name: got $got, want $want" >&2; exit 1; }
  echo "ok   $name ($got)"
}

expect_body() { # name, expected text, curl args...
  local name=$1 want=$2 out
  shift 2
  out=$(curl -sS "$@")
  printf '%s' "$out" | grep -q "$want" || { echo "FAIL $name: body lacks '$want'" >&2; exit 1; }
}

expect_body "home page text" 'Meridian Home Comfort' "$PUBLIC_URL/"
check "GET /" 200 "$PUBLIC_URL/"
expect_body "business page text" 'Meridian AI agent: business view' "$PUBLIC_URL/business"
check "GET /business" 200 "$PUBLIC_URL/business"
check "GET /health" 200 "$PUBLIC_URL/health"
created=$(curl -sS -X POST "$PUBLIC_URL/conversations")
id=$(printf '%s' "$created" | python3 -c 'import json,sys; print(json.load(sys.stdin)["conversationId"])')
check "POST /conversations" 201 -X POST "$PUBLIC_URL/conversations"
check "POST messages" 200 -X POST -H 'Content-Type: application/json' -d '{"text":"hello"}' "$PUBLIC_URL/conversations/$id/messages"
expect_body "unknown conversation code" conversation_not_found -X POST -H 'Content-Type: application/json' -d '{"text":"hi"}' "$PUBLIC_URL/conversations/not-a-real-id/messages"
check "POST unknown conversation" 404 -X POST -H 'Content-Type: application/json' -d '{"text":"hi"}' "$PUBLIC_URL/conversations/not-a-real-id/messages"
