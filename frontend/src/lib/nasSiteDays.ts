import type { WaRecord } from '../store/waStore'

export interface NasFileEntry {
  name: string
  relativePath?: string
  modified?: string
  size?: number
}

export interface SiteDayGroup {
  day: string
  txtFiles: NasFileEntry[]
  nasImages: NasFileEntry[]
  records: WaRecord[]
}

const IMAGE_EXT = /\.(jpe?g|png|webp|gif)$/i

/** Site folder date from `Photo/YYYY-MM-DD/...` or `PJ-xxx_YYYY-MM-DD.txt`. */
export function siteDayFromNasPath(relativePath: string): string | null {
  const normalized = relativePath.replace(/\\/g, '/')
  const inPhoto = normalized.match(/Photo\/(\d{4}-\d{2}-\d{2})(?:\/|$)/i)
  if (inPhoto) return inPhoto[1]
  const inTxtName = normalized.match(/_(\d{4}-\d{2}-\d{2})\.txt$/i)
  if (inTxtName) return inTxtName[1]
  return null
}

/** All site dates linked to a WA record (NAS paths and fallback createdAt). */
export function siteDaysForRecord(record: WaRecord): string[] {
  const days = new Set<string>()
  for (const p of record.nasPhotos || []) {
    const d = siteDayFromNasPath(p)
    if (d) days.add(d)
  }
  if (record.nasSourcePath) {
    const d = siteDayFromNasPath(record.nasSourcePath)
    if (d) days.add(d)
  }
  if (days.size === 0 && record.createdAt) days.add(record.createdAt.slice(0, 10))
  if (days.size === 0) days.add('unknown')
  return [...days]
}

export function buildSiteDayGroups(
  txtFiles: NasFileEntry[],
  nasImages: NasFileEntry[],
  records: WaRecord[],
): SiteDayGroup[] {
  const map = new Map<string, SiteDayGroup>()

  const ensure = (day: string): SiteDayGroup => {
    let g = map.get(day)
    if (!g) {
      g = { day, txtFiles: [], nasImages: [], records: [] }
      map.set(day, g)
    }
    return g
  }

  for (const f of txtFiles) {
    const path = f.relativePath || f.name
    const day = siteDayFromNasPath(path) || f.modified?.slice(0, 10) || 'unknown'
    ensure(day).txtFiles.push(f)
  }

  for (const f of nasImages) {
    if (!IMAGE_EXT.test(f.name)) continue
    const path = f.relativePath || f.name
    const day = siteDayFromNasPath(path) || f.modified?.slice(0, 10) || 'unknown'
    ensure(day).nasImages.push(f)
  }

  for (const r of records) {
    for (const day of siteDaysForRecord(r)) {
      const bucket = ensure(day).records
      if (!bucket.some((x) => x.id === r.id)) bucket.push(r)
    }
  }

  for (const g of map.values()) {
    g.txtFiles.sort((a, b) => (b.modified || '').localeCompare(a.modified || ''))
    g.nasImages.sort((a, b) => (a.relativePath || a.name).localeCompare(b.relativePath || b.name))
    g.records.sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''))
  }

  return [...map.values()]
    .filter((g) => g.txtFiles.length > 0 || g.nasImages.length > 0 || g.records.length > 0)
    .sort((a, b) => b.day.localeCompare(a.day))
}

export function basenamePath(p: string): string {
  const parts = p.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || p
}

/** Match WA upload path to a NAS relative path by filename. */
export function waPhotoForNasFile(nasRelative: string, records: WaRecord[]): string | undefined {
  const base = basenamePath(nasRelative).toLowerCase()
  for (const r of records) {
    for (const p of r.photos || []) {
      if (basenamePath(p).toLowerCase() === base) return p
    }
  }
  return undefined
}
