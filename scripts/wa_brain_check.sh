#!/usr/bin/env bash
# Quick WA brain / double-reply risk check for Demo Mini.
set -euo pipefail
BASE="${1:-http://127.0.0.1:5001}"
URL="${BASE%/}/api/wa/brain/status"
echo "GET $URL"
BODY="$(curl -sf "$URL")"
echo "$BODY" | python3 -m json.tool
RISK="$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('doubleReplyRisk','?'))")"
NOTIFY="$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('loomInboundNotifyUrlConfigured', False))")"
echo "---"
echo "doubleReplyRisk=$RISK (want low)"
echo "loomInboundNotifyUrlConfigured=$NOTIFY (want true when Gateway=true)"
if [[ "$RISK" == "high" ]]; then
  echo "FAIL: fix Wakka single consumer + LOOM_WA_INBOUND_NOTIFY_URL (see docs/DEMO_WA_SETUP.md)" >&2
  exit 1
fi
echo "OK"
