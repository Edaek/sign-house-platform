"""Traditional Chinese NAS status lines for WhatsApp Loomy (human + agent context)."""
from __future__ import annotations

from typing import Any, Mapping, Optional


def format_wa_nas_summary_zh(
    st: Mapping[str, Any],
    *,
    open_pool_count: Optional[int] = None,
) -> str:
    """One short paragraph from nas_mount.status() fields."""
    enabled = bool(st.get('enabled'))
    connected = bool(st.get('connected'))
    degraded = bool(st.get('degraded'))
    folders = int(st.get('foldersFound') or 0)
    cache_stale = bool(st.get('foldersCacheStale'))
    mongo_n = int(st.get('mongoActiveProjects') or 0)
    parts: list[str] = []
    if not enabled:
        parts.append('NAS 未在設定中啟用。')
    elif not connected:
        parts.append('共享盤尚未掛載或無法存取。')
    else:
        parts.append('共享盤已掛載。')
        if degraded:
            parts.append('SMB 回應偏慢（degraded）。')
        if folders > 0 and not cache_stale:
            parts.append(f'快取約 {folders} 個工地資料夾。')
        elif cache_stale:
            parts.append(
                '資料夾清單快取刷新中（掃描可能較慢）；Web 與相片歸類仍可用。'
            )
        else:
            parts.append(f'快取約 {folders} 個工地資料夾。')
    if mongo_n > 0:
        parts.append(f'Mongo 活躍專案 {mongo_n} 個。')
    if open_pool_count is not None and open_pool_count >= 0:
        parts.append(f'你尚有 {open_pool_count} 張待歸類照片。')
    return ' '.join(parts)
