#!/usr/bin/env bash
# End-to-end tests: starts the fake LLM endpoint and a Polya server on a temp folder (with a copy of
# tests/sample_project as the codebase), then drives the agent bridge and a real browser.
# Needs: `node` with the `playwright` package and a Chromium; `pip install matplotlib pandas`.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== tests/test_source.py"; python tests/test_source.py | tail -1
TMP=$(mktemp -d); SHOTS=${1:-$TMP/shots}; mkdir -p "$SHOTS"; cp -r tests/sample_project "$TMP/proj"
python tests/fake_llm.py 8765 >"$TMP/fake.log" 2>&1 & FAKE=$!
POLYA_BASE_URL=http://127.0.0.1:8765/v1 POLYA_API_KEY=x POLYA_MODEL=fake python -m polya --dir "$TMP/dialogs" --project "$TMP/proj" --port 5001 >"$TMP/server.log" 2>&1 & SRV=$!
trap 'kill $FAKE $SRV 2>/dev/null || true' EXIT
for i in $(seq 40); do curl -sf -o /dev/null http://127.0.0.1:5001/ && break; sleep 0.5; done
for t in tests/e2e/0[123]_*.js; do echo "== $t"; node "$t" "$SHOTS"; done
echo "== tests/agent_bridge.py"; python tests/agent_bridge.py "$TMP/dialogs/.polya-agent-token"
echo "== tests/e2e/04_codebase.js"; node tests/e2e/04_codebase.js "$SHOTS" "$TMP/proj"
echo "== tests/e2e/05_sandbox.js"; node tests/e2e/05_sandbox.js "$SHOTS"; rm -f ~/polya_written_by_ai*.txt
echo "== tests/e2e/06_bulk_runs.js"; node tests/e2e/06_bulk_runs.js
echo "== tests/e2e/07_other_dialogs.js"; node tests/e2e/07_other_dialogs.js
echo "== tests/e2e/08_roundtrip.js"; rm -rf "$TMP/proj/acme"; cp -r tests/sample_project/acme "$TMP/proj/acme"; node tests/e2e/08_roundtrip.js "$TMP/proj" "$SHOTS"
echo "Screenshots in $SHOTS"
