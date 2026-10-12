#!/usr/bin/env bash
# Cursor stdio entry — keeps cwd and venv on PATH.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
exec "${ROOT}/.venv/bin/python" -m mcp_wa.server
