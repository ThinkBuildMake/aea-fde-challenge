#!/usr/bin/env bash
# Secret scan gate: gitleaks exits 0 when its internal git call fails, so also
# require that it scanned every commit in the history.
set -uo pipefail
GITLEAKS=${GITLEAKS:-gitleaks}

out=$("$GITLEAKS" git --no-banner --no-color --redact --exit-code 1 . 2>&1)
status=$?
printf '%s\n' "$out"
[ "$status" -eq 0 ] || exit "$status"

want=$(git rev-list --all --count)
got=$(printf '%s\n' "$out" | sed -n 's/.* \([0-9][0-9]*\) commits scanned.*/\1/p' | tail -n 1)
if [ -z "$got" ] || [ "$got" != "$want" ]; then
  echo "FAIL secret scan covered ${got:-0} of $want commits" >&2
  exit 1
fi
