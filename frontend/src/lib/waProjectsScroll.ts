/** Persist WA Projects list scroll per bucket (session tab). */

const PREFIX = 'signhouse.wa.projects.scroll.v1'

export function waProjectsScrollStorageKey(bucket: string | null | undefined): string {
  const b = (bucket || '').trim()
  return `${PREFIX}:${b || '__root__'}`
}

export function saveWaProjectsScroll(bucket: string | null | undefined): void {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.setItem(waProjectsScrollStorageKey(bucket), String(Math.round(window.scrollY)))
  } catch {
    /* quota / private mode */
  }
}

export function readWaProjectsScroll(bucket: string | null | undefined): number {
  if (typeof window === 'undefined') return 0
  try {
    const raw = sessionStorage.getItem(waProjectsScrollStorageKey(bucket))
    if (raw == null) return 0
    const n = parseInt(raw, 10)
    return Number.isFinite(n) && n > 0 ? n : 0
  } catch {
    return 0
  }
}
