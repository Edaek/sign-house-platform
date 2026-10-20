import type { WaProject } from '../store/waStore'

const RANGE_BUCKET_RE = /^PJ-(\d+)-(\d+)$/i
/** Matches backend SITE_FOLDER_CODE_RE (folder name → site number). */
const SITE_FOLDER_CODE_RE = /^PJ-(\d{1,6})(?:$|\s|_.*)/i

/** NAS range bucket e.g. PJ-2800-2899 (same rule as backend is_range_folder_code). */
export function isRangeBucketCode(code: string): boolean {
  const b = parseRangeBounds(code)
  return b != null && b.hi > b.lo
}

const T_RANGE_BUCKET_RE = /^T-\d+-\d+$/i

/** Top-level NAS bucket folder (PJ-lo-hi or T-lo-hi) — not a site project code. */
export function isNasBucketFolderCode(code: string): boolean {
  const c = (code || '').trim()
  return isRangeBucketCode(c) || T_RANGE_BUCKET_RE.test(c)
}

export function nasFolderNameDiffersFromCode(project: Pick<WaProject, 'code' | 'nasFolderName'>): boolean {
  const code = (project.code || '').trim()
  const folder = (project.nasFolderName || '').trim()
  return Boolean(folder && code && folder.toUpperCase() !== code.toUpperCase())
}

export function parseRangeBounds(code: string): { lo: number; hi: number } | null {
  const m = (code || '').trim().match(RANGE_BUCKET_RE)
  if (!m) return null
  let lo = parseInt(m[1], 10)
  let hi = parseInt(m[2], 10)
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

export function siteNumberFromProject(project: WaProject): number | null {
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

export function buildProjectBuckets(projects: WaProject[]): WaProjectBucket[] {
  const ranges = projects.filter((p) => isRangeBucketCode(p.code))
  const sites = projects.filter((p) => !isRangeBucketCode(p.code))
  const rangeByCode = new Map(ranges.map((r) => [r.code.toUpperCase(), r]))
  const sitesByBucket = new Map<string, WaProject[]>()

  const standaloneLabels = new Map<string, string>()

  for (const site of sites) {
    const parentBucket = (site.nasParentBucket || '').trim()
    let bucketKey: string
    if (parentBucket) {
      bucketKey = isRangeBucketCode(parentBucket)
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
        bucketKey = inferRangeBucketCode(num)
        for (const r of ranges) {
          const b = parseRangeBounds(r.code)
          if (b && num >= b.lo && num <= b.hi) {
            bucketKey = r.code.toUpperCase()
            break
          }
        }
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
    if (!adminProject && isRangeBucketCode(code)) {
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
    const key = isRangeBucketCode(name) ? name.toUpperCase() : `__standalone:${name.toUpperCase()}`
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
