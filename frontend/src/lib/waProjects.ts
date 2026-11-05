import type { WaProject } from '../store/waStore'

const RANGE_BUCKET_RE = /^PJ-(\d+)-(\d+)$/i
/** Matches backend SITE_FOLDER_CODE_RE (folder name → site number). */
const SITE_FOLDER_CODE_RE = /^PJ-(\d{1,6})(?:$|\s|_.*)/i

/** NAS range bucket e.g. PJ-2800-2899 (same rule as backend is_range_folder_code). */
export function isRangeBucketCode(code: string): boolean {
  const b = parseRangeBounds(code)
  return b != null && b.hi > b.lo
}

const GENERIC_RANGE_BUCKET_RE = /^(.+)-(\d+)-(\d+)$/i

/** Top-level NAS bucket folder — site number lo-hi range (any prefix). */
export function isNasBucketFolderCode(code: string): boolean {
  return parseRangeBounds(code) != null
}

/** UI ?bucket= key for a physical NAS root directory (matches backend web_bucket_key_for_nas_root). */
export function webBucketKeyForNasRoot(nasDirName: string): string {
  const name = (nasDirName || '').trim()
  if (!name) return name
  if (isNasBucketFolderCode(name)) return name.toUpperCase()
  return `__standalone:${name.toUpperCase()}`
}

export function physicalBucketName(bucketCode: string): string {
  return isStandaloneBucketCode(bucketCode)
    ? standaloneBucketDisplayCode(bucketCode).toUpperCase()
    : (bucketCode || '').trim().toUpperCase()
}

export function nasFolderNameDiffersFromCode(project: Pick<WaProject, 'code' | 'nasFolderName'>): boolean {
  const code = (project.code || '').trim()
  const folder = (project.nasFolderName || '').trim()
  return Boolean(folder && code && folder.toUpperCase() !== code.toUpperCase())
}

export function parseRangeBounds(code: string): { lo: number; hi: number } | null {
  const trimmed = (code || '').trim()
  const pj = trimmed.match(RANGE_BUCKET_RE)
  const m = pj || trimmed.match(GENERIC_RANGE_BUCKET_RE)
  if (!m) return null
  let lo = parseInt(m[pj ? 1 : 2], 10)
  let hi = parseInt(m[pj ? 2 : 3], 10)
  if (lo > hi) [lo, hi] = [hi, lo]
  return { lo, hi }
}

export function siteNumberFromCode(code: string): number | null {
  const trimmed = (code || '').trim()
  if (!trimmed || isRangeBucketCode(trimmed)) return null
  let m = trimmed.match(SITE_FOLDER_CODE_RE)
  if (m) return parseInt(m[1], 10)
  m = trimmed.match(/^[Pp][Jj][-]?(\d{1,6})$/)
  if (m) return parseInt(m[1], 10)
  if (/^\d{3,6}$/.test(trimmed)) return parseInt(trimmed, 10)
  return null
}

export function siteNumberFromProject(
  project: Pick<WaProject, 'code' | 'nasFolderName'>,
): number | null {
  for (const raw of [project.code, project.nasFolderName]) {
    const n = siteNumberFromCode(raw || '')
    if (n != null) return n
  }
  return null
}

/** Top-level NAS folder label when project is not under a PJ-lo-hi range. */
export function standaloneFolderLabel(project: WaProject): string {
  return (project.nasFolderName || project.code || project.id).trim()
}

export function isStandaloneBucketCode(code: string): boolean {
  return code.startsWith('__standalone:')
}

export function standaloneBucketDisplayCode(code: string): string {
  return isStandaloneBucketCode(code) ? code.slice('__standalone:'.length) : code
}

/** NAS parent folder when creating a project from a bucket drill-down view. */
export function parentBucketCodeForNas(selectedBucketCode: string | null): string | undefined {
  if (!selectedBucketCode) return undefined
  if (isStandaloneBucketCode(selectedBucketCode)) {
    return standaloneBucketDisplayCode(selectedBucketCode)
  }
  return selectedBucketCode
}

export function bucketFolderLabel(selectedBucketCode: string): string {
  return parentBucketCodeForNas(selectedBucketCode) ?? selectedBucketCode
}

/** Map NAS parent folder label → `?bucket=` value on /wa/projects. */
export function bucketCodeForProjectsUrl(
  nasParentBucket: string | undefined,
  projects: WaProject[],
): string | null {
  const parent = (nasParentBucket || '').trim()
  if (!parent) return null
  const buckets = buildProjectBuckets(projects)
  const direct = buckets.find(
    (b) =>
      b.code.toUpperCase() === parent.toUpperCase()
      || bucketFolderLabel(b.code).toUpperCase() === parent.toUpperCase()
      || (isStandaloneBucketCode(b.code)
        && standaloneBucketDisplayCode(b.code).toUpperCase() === parent.toUpperCase()),
  )
  if (direct) return direct.code
  if (isRangeBucketCode(parent)) return parent.toUpperCase()
  return `__standalone:${parent.toUpperCase()}`
}

export function waProjectsListPath(bucketCode: string | null | undefined): string {
  if (!bucketCode?.trim()) return '/wa/projects'
  return `/wa/projects?${new URLSearchParams({ bucket: bucketCode.trim() }).toString()}`
}

export function inferRangeBucketCode(siteNum: number): string {
  const lo = Math.floor(siteNum / 100) * 100
  return `PJ-${lo}-${lo + 99}`
}

export type WaProjectBucket = {
  code: string
  /** Secondary line under folder code (usually NAS folder label). */
  label: string
  projectId?: string
  siteProjects: WaProject[]
}

/** Group site projects under PJ-lo-hi buckets (matches NAS outer folders). */
/** Folder container project (e.g. LIGHT) — not listed as its own child inside the bucket. */
export function isBucketContainerSite(bucketCode: string, project: WaProject): boolean {
  if (isStandaloneBucketCode(bucketCode)) {
    const bucketName = standaloneBucketDisplayCode(bucketCode).toUpperCase()
    return (project.code || '').toUpperCase() === bucketName
  }
  if (isRangeBucketCode(bucketCode)) {
    return (project.code || '').toUpperCase() === bucketCode.toUpperCase()
  }
  return false
}

export function bucketSiteProjects(bucket: WaProjectBucket): WaProject[] {
  return bucket.siteProjects.filter((p) => !isBucketContainerSite(bucket.code, p))
}

export type NasRootBucketRow = {
  bucketCode: string
  nasName: string
  childCount?: number
}

/** Merge live NAS top-level folders into the bucket grid (NAS-only buckets appear before sync). */
export function mergeProjectsWithNasRootBuckets(
  projects: WaProject[],
  nasRoots: NasRootBucketRow[],
): { buckets: WaProjectBucket[]; nasFolderCounts: Record<string, number> } {
  const buckets = buildProjectBuckets(projects)
  const byCode = new Map(buckets.map((b) => [b.code, b]))
  const physSeen = new Set(buckets.map((b) => physicalBucketName(b.code)))
  const nasFolderCounts: Record<string, number> = {}
  for (const row of nasRoots) {
    const nasName = (row.nasName || '').trim()
    const code = (row.bucketCode || webBucketKeyForNasRoot(nasName)).trim()
    if (!code) continue
    const phys = physicalBucketName(code)
    if (row.childCount != null) {
      const existingKey = [...byCode.entries()].find(
        ([k]) => physicalBucketName(k) === phys,
      )?.[0]
      nasFolderCounts[existingKey ?? code] = row.childCount
    }
    if (physSeen.has(phys)) continue
    physSeen.add(phys)
    byCode.set(code, {
      code,
      label: nasName || standaloneBucketDisplayCode(code),
      siteProjects: [],
    })
  }
  const merged = [...byCode.values()].sort((a, b) => a.code.localeCompare(b.code))
  return { buckets: merged, nasFolderCounts }
}

export function buildProjectBuckets(projects: WaProject[]): WaProjectBucket[] {
  const ranges = projects.filter((p) => isNasBucketFolderCode(p.code))
  const sites = projects.filter((p) => !isNasBucketFolderCode(p.code))
  const rangeByCode = new Map(ranges.map((r) => [r.code.toUpperCase(), r]))
  const sitesByBucket = new Map<string, WaProject[]>()

  const standaloneLabels = new Map<string, string>()

  for (const site of sites) {
    const parentBucket = (site.nasParentBucket || '').trim()
    let bucketKey: string
    if (parentBucket) {
      bucketKey = isNasBucketFolderCode(parentBucket)
        ? parentBucket.toUpperCase()
        : `__standalone:${parentBucket.toUpperCase()}`
      if (!standaloneLabels.has(parentBucket.toUpperCase())) {
        standaloneLabels.set(parentBucket.toUpperCase(), parentBucket)
      }
    } else {
      const num = siteNumberFromProject(site)
      if (num == null) {
        const label = standaloneFolderLabel(site)
        const norm = label.toUpperCase()
        bucketKey = `__standalone:${norm}`
        if (!standaloneLabels.has(norm)) standaloneLabels.set(norm, label)
      } else {
        let best: { key: string; span: number } | null = null
        for (const r of ranges) {
          const b = parseRangeBounds(r.code)
          if (b && num >= b.lo && num <= b.hi) {
            const span = b.hi - b.lo
            // Prefer the outer NAS bucket (e.g. PJ-3000-3999 over PJ-3000-3099 for site 3047).
            if (!best || span > best.span) {
              best = { key: r.code.toUpperCase(), span }
            }
          }
        }
        bucketKey = best?.key ?? inferRangeBucketCode(num)
      }
    }
    if (!sitesByBucket.has(bucketKey)) sitesByBucket.set(bucketKey, [])
    sitesByBucket.get(bucketKey)!.push(site)
  }

  const bucketCodes = new Set<string>([
    ...ranges.map((r) => r.code.toUpperCase()),
    ...sitesByBucket.keys(),
  ])

  const buckets: WaProjectBucket[] = []
  for (const code of [...bucketCodes].sort()) {
    const siteList = sitesByBucket.get(code) || []
    const rangeProj = rangeByCode.get(code.toUpperCase())
    let label: string
    if (rangeProj) {
      label = rangeProj.nasFolderName || code
    } else if (isStandaloneBucketCode(code)) {
      label = standaloneLabels.get(code.slice('__standalone:'.length)) || standaloneBucketDisplayCode(code)
    } else {
      label = code
    }
    let adminProject = rangeProj
    if (!adminProject) {
      adminProject = siteList.find((p) => isBucketContainerSite(code, p))
    }
    if (!adminProject && isStandaloneBucketCode(code)) {
      const bn = standaloneBucketDisplayCode(code).toUpperCase()
      adminProject = projects.find((p) => (p.code || '').toUpperCase() === bn)
    }
    if (!adminProject && isNasBucketFolderCode(code)) {
      adminProject = projects.find((p) => (p.code || '').toUpperCase() === code.toUpperCase())
    }
    buckets.push({
      code,
      label,
      projectId: adminProject?.id,
      siteProjects: siteList,
    })
  }

  return buckets
}

/** Top-level NAS directory names merged into manage-project folder list. */
export function mergeNasRootBuckets(buckets: WaProjectBucket[], rootNames: string[]): WaProjectBucket[] {
  const byKey = new Map(buckets.map((b) => [b.code.toUpperCase(), b]))
  for (const raw of rootNames) {
    const name = (raw || '').trim()
    if (!name) continue
    const key = webBucketKeyForNasRoot(name)
    const phys = physicalBucketName(key)
    if ([...byKey.values()].some((b) => physicalBucketName(b.code) === phys)) continue
    if (byKey.has(key.toUpperCase())) continue
    byKey.set(key.toUpperCase(), {
      code: key,
      label: name,
      siteProjects: [],
    })
  }
  return [...byKey.values()].sort((a, b) => a.label.localeCompare(b.label))
}

export function bucketAdminProject(bucket: WaProjectBucket, projects: WaProject[]): WaProject | undefined {
  if (bucket.projectId) {
    return projects.find((p) => p.id === bucket.projectId)
  }
  const code = isStandaloneBucketCode(bucket.code) ? standaloneBucketDisplayCode(bucket.code) : bucket.code
  return projects.find((p) => (p.code || '').toUpperCase() === code.toUpperCase())
}

export function projectMatchesQuery(project: WaProject, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const folder = (project.nasFolderName || '').toLowerCase()
  return (
    project.code.toLowerCase().includes(q) ||
    (folder && folder.includes(q)) ||
    (project.location?.toLowerCase().includes(q) ?? false) ||
    project.status.toLowerCase().includes(q) ||
    project.stage.toLowerCase().includes(q)
  )
}

/** Primary display: NAS folder name when it differs from code, else code. */
export function formatWaProjectLabel(project: Pick<WaProject, 'code' | 'nasFolderName'>): string {
  const code = (project.code || '').trim()
  const folder = (project.nasFolderName || '').trim()
  if (folder && folder.toLowerCase() !== code.toLowerCase()) {
    return folder
  }
  return code
}

/** Detail page title suffix — avoids "PJ-3002 — PJ-3002 中醫院…" duplication. */
export function formatWaProjectTitleSuffix(
  project: Pick<WaProject, 'code' | 'nasFolderName'>,
): string | null {
  const code = (project.code || '').trim()
  const folder = (project.nasFolderName || '').trim()
  if (!folder || folder.toUpperCase() === code.toUpperCase()) return null
  if (folder.toUpperCase().startsWith(code.toUpperCase())) {
    const rest = folder.slice(code.length).trim().replace(/^[-–—]\s*/, '')
    return rest || null
  }
  return folder
}

/** Collapse duplicate NAS folder rows (same label, different Mongo stubs). */
export function dedupeBucketSiteProjects(projects: WaProject[]): WaProject[] {
  const byFolder = new Map<string, WaProject>()
  const score = (p: WaProject) =>
    (p.id.startsWith('nas:') ? 0 : 1000) + (p.totalRecords ?? 0) + (p.nasFolderName?.length ?? 0)

  for (const p of projects) {
    const k = (p.nasFolderName || p.code || p.id).trim().toLowerCase()
    if (!k) continue
    const prev = byFolder.get(k)
    if (!prev || score(p) > score(prev)) {
      byFolder.set(k, p)
    }
  }
  return [...byFolder.values()].sort((a, b) =>
    (a.nasFolderName || a.code).localeCompare(b.nasFolderName || b.code, undefined, {
      sensitivity: 'base',
    }),
  )
}

export function bucketSiteProjectKey(project: WaProject): string {
  return project.id || `nas:${(project.nasFolderName || project.code || 'unknown').trim()}`
}

export function filterWaProjects(
  projects: WaProject[],
  query: string,
  stage?: string
): WaProject[] {
  return projects.filter((project) => {
    if (stage && project.stage !== stage) return false
    return projectMatchesQuery(project, query)
  })
}
