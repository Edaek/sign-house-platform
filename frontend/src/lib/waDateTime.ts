/** WA UI timestamps: Mongo/NAS store UTC naive ISO; display in Hong Kong time. */
export const WA_TIME_ZONE = 'Asia/Hong_Kong'

/** Parse API datetimes (UTC naive ISO from Mongo/NAS) as instant in UTC. */
export function parseAppDateTime(value: string | Date | null | undefined): Date {
  if (value == null || value === '') return new Date(NaN)
  if (value instanceof Date) return value
  const s = String(value).trim()
  if (!s) return new Date(NaN)
  if (/[Zz]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s)) {
    return new Date(s)
  }
  const normalized = s.includes('T') ? `${s}Z` : `${s}T00:00:00Z`
  return new Date(normalized)
}

export function formatDateTimeHK(value: string | Date | null | undefined): string {
  const d = parseAppDateTime(value)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-HK', {
    timeZone: WA_TIME_ZONE,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatDateHK(value: string | Date | null | undefined): string {
  const d = parseAppDateTime(value)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('zh-HK', {
    timeZone: WA_TIME_ZONE,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  })
}

export function formatNasModifiedHK(modified: string | null | undefined): string {
  if (!modified) return ''
  const formatted = formatDateTimeHK(modified)
  return formatted ? `NAS ${formatted} (香港時間)` : ''
}
