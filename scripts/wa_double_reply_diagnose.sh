#!/usr/bin/env bash
# Deep check: who can send WhatsApp (Sign House vs Loom) and common double-bubble causes.
set -euo pipefail
BASE="${1:-http://127.0.0.1:5001}"
LOG="${2:-}"

echo "=== brain/status ==="
BODY="$(curl -sf "${BASE%/}/api/wa/brain/status")"
echo "$BODY" | python3 -m json.tool

echo ""
echo "=== summary ==="
python3 - <<'PY' "$BODY"
import json, sys
b = json.loads(sys.argv[1])
audit = b.get("doubleReplyAudit") or {}
print(f"brain={b.get('brain')} doubleReplyRisk={b.get('doubleReplyRisk')}")
print(f"signHouseCanSendWhatsapp={audit.get('signHouseCanSendWhatsapp')} (want False)")
print(f"gatewaySchedulesLoomHttpPost={audit.get('gatewaySchedulesLoomHttpPost')} (want False for Wakka→Loom-only)")
print(f"signHouseRelayEnabled={audit.get('signHouseRelayEnabled')} (want False)")
print(f"loomInboundNotifyExplicit={b.get('loomInboundNotifyExplicit')}")
print(f"loomPlatformChatFallbackAllowed={b.get('loomPlatformChatFallbackAllowed')}")
if b.get("doubleReplyRisk") == "high":
    print("RISK: Sign House or Gateway HTTP may stack with Loom Turn — see duplicateReplyHints")
elif audit.get("signHouseCanSendWhatsapp") is False and not audit.get("gatewaySchedulesLoomHttpPost"):
    print("OK: Two bubbles are NOT from Sign House relay/notify — check NOps Loom Turn outbound count")
PY

if [[ -n "$LOG" && -f "$LOG" ]]; then
  echo ""
  echo "=== log grep (Sign House WA sends) ==="
  rg -n '\[Wakka\] Sign House →|\[LoomNotify\] Sent WA' "$LOG" | tail -20 || echo "(no matches — good for loom-only)"
fi
