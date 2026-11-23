#!/usr/bin/env bash
# End-to-end tests: starts the fake LLM endpoint and a Polya server on a temp folder, then drives
# a real browser with Playwright (needs `node` with the `playwright` package and a Chromium).
set -euo pipefail
cd "$(dirname "$0")/.."
TMP=$(mktemp -d); SHOTS=${1:-$TMP/shots}; mkdir -p "$SHOTS"
python tests/fake_llm.py 8765 >"$TMP/fake.log" 2>&1 & FAKE=$!
POLYA_BASE_URL=http://127.0.0.1:8765/v1 POLYA_API_KEY=x POLYA_MODEL=fake python -m polya --dir "$TMP/dialogs" --port 5001 >"$TMP/server.log" 2>&1 & SRV=$!
trap 'kill $FAKE $SRV 2>/dev/null || true' EXIT
for i in $(seq 40); do curl -sf -o /dev/null http://127.0.0.1:5001/ && break; sleep 0.5; done
for t in tests/e2e/*.js; do echo "== $t"; node "$t" "$SHOTS"; done
echo "Screenshots in $SHOTS"
