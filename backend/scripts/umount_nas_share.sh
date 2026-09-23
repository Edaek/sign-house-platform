#!/usr/bin/env bash
set -euo pipefail
MOUNT_POINT="/Volumes/Project Photo for Installation"
if mount | grep -F " on ${MOUNT_POINT} " >/dev/null 2>&1; then
  diskutil unmount "$MOUNT_POINT" || umount "$MOUNT_POINT"
  echo "Unmounted ${MOUNT_POINT}"
else
  echo "Not mounted: ${MOUNT_POINT}"
fi
