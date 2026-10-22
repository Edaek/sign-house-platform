#!/usr/bin/env bash
# Mount client NAS so NAS_WATCH_DIR exists on THIS Mac (same path as Mac Mini).
#
# Usage (run in Terminal — may prompt for Mac login password once):
#   ./scripts/mount_nas_share.sh              # SMB direct to 192.168.123.202
#   ./scripts/mount_nas_share.sh --via-tunnel # Finder SMB via SSH tunnel on Mini (recommended on MacBook)
#   ./scripts/mount_nas_share.sh --via-mini   # SSHFS via haymondmac-mini (needs: brew install macfuse sshfs)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
MOUNT_POINT="/Volumes/Project Photo for Installation"
NAS_IP="${NAS_SMB_HOST:-192.168.123.202}"
SHARE_NAME="Project Photo for Installation"
MINI_HOST="${MINI_HOST:-100.127.201.0}"
MINI_USER="${MINI_USER:-HaymondHo}"
VIA_MINI=false
VIA_TUNNEL=false
case "${1:-}" in
  --via-mini) VIA_MINI=true ;;
  --via-tunnel) VIA_TUNNEL=true ;;
esac

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

read_env() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2- | sed 's/^["'\''"]//;s/["'\''"]$//'
}

NAS_USER="$(read_env NAS_USER)"
NAS_PASSWORD="$(read_env NAS_PASSWORD)"

if [[ -z "$NAS_USER" || -z "$NAS_PASSWORD" ]]; then
  echo "NAS_USER and NAS_PASSWORD must be set in .env" >&2
  exit 1
fi

if mount | grep -F " on ${MOUNT_POINT} " >/dev/null 2>&1; then
  echo "Already mounted: ${MOUNT_POINT}"
  exit 0
fi

# Empty local folder at MOUNT_POINT makes macOS mount to "…-1" — backend will stay Disconnected.
if [[ -d "$MOUNT_POINT" ]] && ! mount | grep -F " on ${MOUNT_POINT} " >/dev/null 2>&1; then
  echo "Removing stale placeholder (not an SMB mount): ${MOUNT_POINT}"
  rm -rf "$MOUNT_POINT" || sudo rm -rf "$MOUNT_POINT"
fi

if ! $VIA_TUNNEL && ! ping -c 1 -W 2 "$NAS_IP" >/dev/null 2>&1; then
  echo "Cannot reach NAS at ${NAS_IP}. Check Tailscale / VPN, or use: $0 --via-tunnel" >&2
  exit 1
fi

if ! $VIA_TUNNEL && [[ ! -d "$MOUNT_POINT" ]]; then
  echo "Creating mount point (may ask for your Mac login password)..."
  sudo mkdir -p "$MOUNT_POINT"
  sudo chown "$(whoami)" "$MOUNT_POINT"
fi

ensure_mount_point() {
  if [[ ! -d "$MOUNT_POINT" ]]; then
    echo "Creating mount point (Mac login password required)..."
    sudo mkdir -p "$MOUNT_POINT"
    sudo chown "$(whoami)" "$MOUNT_POINT"
  fi
}

WATCH="${MOUNT_POINT}/${SHARE_NAME}"

mount_via_finder() {
  local smb_host="$1"
  local smb_port="${2:-445}"
  local url="smb://${smb_host}:${smb_port}/${SHARE_NAME// /%20}"
  osascript <<APPLESCRIPT
try
  mount volume "$url" as user name "$NAS_USER" with password "$NAS_PASSWORD"
on error errMsg number errNum
  error "Finder mount failed (" & errNum & "): " & errMsg
end try
APPLESCRIPT
}

if $VIA_TUNNEL; then
  TUNNEL_PORT="${NAS_TUNNEL_PORT:-1445}"
  if ! pgrep -f "127.0.0.1:${TUNNEL_PORT}:192.168.123.202:445" >/dev/null 2>&1; then
    echo "Opening SSH tunnel ${MINI_USER}@${MINI_HOST} → 192.168.123.202:445 (local ${TUNNEL_PORT})..."
    ssh -f -N -o ExitOnForwardFailure=yes \
      -L "127.0.0.1:${TUNNEL_PORT}:192.168.123.202:445" \
      "${MINI_USER}@${MINI_HOST}"
  fi
  echo "Mounting via Finder (SMB through tunnel)..."
  mount_via_finder "127.0.0.1" "$TUNNEL_PORT"
elif $VIA_MINI; then
  if ! command -v sshfs >/dev/null 2>&1; then
    echo "Install: brew install macfuse sshfs  (macFUSE installer needs your password)" >&2
    exit 1
  fi
  ensure_mount_point
  REMOTE="/Volumes/Project Photo for Installation"
  echo "Mounting via SSH ${MINI_USER}@${MINI_HOST}:${REMOTE} ..."
  sshfs "${MINI_USER}@${MINI_HOST}:${REMOTE}" "$MOUNT_POINT" \
    -o reconnect,volname="${SHARE_NAME}",follow_symlinks
else
  ENCODED_SHARE="${SHARE_NAME// /%20}"
  SMB_URL="//${NAS_USER}:${NAS_PASSWORD}@${NAS_IP}/${ENCODED_SHARE}"
  ensure_mount_point
  echo "Mounting SMB ${NAS_IP} to ${MOUNT_POINT} ..."
  if ! mount_smbfs "$SMB_URL" "$MOUNT_POINT"; then
    echo "" >&2
    echo "SMB direct failed. Retry: $0 --via-tunnel" >&2
    echo "Or Finder Cmd+K → smb://${NAS_IP}/${ENCODED_SHARE} (user ${NAS_USER})" >&2
    exit 1
  fi
fi
if [[ -d "$WATCH" ]]; then
  echo "OK: NAS_WATCH_DIR path exists: ${WATCH}"
else
  echo "Mounted, but inner folder missing: ${WATCH}" >&2
  exit 1
fi
