import type { WaRecord } from '../store/waStore'

const PLACEHOLDER = '[pool media]'

/** User classify remark (excludes generic pool placeholder). */
export function recordRemarkText(record: WaRecord): string {
  const fromApi = record.remark?.trim()
  if (fromApi) return fromApi
  const raw = record.rawMessage?.trim() ?? ''
  if (!raw || raw.toLowerCase() === PLACEHOLDER) return ''
  return raw
}

export function recordRemarkDisplay(record: WaRecord): string {
  return recordRemarkText(record) || '—'
}
