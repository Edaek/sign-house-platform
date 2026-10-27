#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

if [[ ! -d "$BACKEND/.venv" ]]; then
  python3 -m venv "$BACKEND/.venv"
fi
"$BACKEND/.venv/bin/pip" install -U pip
"$BACKEND/.venv/bin/pip" install -r "$BACKEND/requirements.txt"

if [[ ! -f "$BACKEND/.env" ]]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  echo "Created backend/.env — edit MONGO_URI and JWT_SECRET_KEY (must match Sign House main app users DB)."
fi

(cd "$FRONTEND" && npm install)

echo "Done. Start with: ./scripts/dev.sh"
