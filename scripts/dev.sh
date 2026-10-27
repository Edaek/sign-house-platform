#!/usr/bin/env bash
# mcp-v3 branch: backend (API + /mcp) + Vite frontend
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PY="${BACKEND}/.venv/bin/python"
FALLBACK="${SIGNHOUSE_V3_VENV:-$BACKEND/.venv}/bin/python"

for candidate in "$PY" "$FALLBACK"; do
  if [[ -x "$candidate" ]] && PYTHONPATH="$BACKEND" "$candidate" -c "from app import create_app" 2>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [[ ! -x "$PY" ]]; then
  echo "Create backend/.venv and pip install -r backend/requirements.txt" >&2
  exit 1
fi

if [[ ! -f "$BACKEND/.env" ]]; then
  echo "Copy backend/.env.example to backend/.env and configure MONGO_URI, etc." >&2
  exit 1
fi

export PORT="${PORT:-5002}"
export MCP_HTTP_MOUNT_PREFIX="${MCP_HTTP_MOUNT_PREFIX:-/mcp}"

cleanup() { kill $(jobs -p) 2>/dev/null || true; }
trap cleanup EXIT

echo "Backend (API + MCP) → http://127.0.0.1:${PORT}"
echo "Web UI             → http://127.0.0.1:3000"

(cd "$BACKEND" && PYTHONPATH=. "$PY" run.py) &
sleep 2
(cd "$FRONTEND" && npm run dev) &
wait
