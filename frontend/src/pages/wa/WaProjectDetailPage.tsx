import { useCallback, useEffect, useRef, useState, useMemo } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useWaStore } from '../../store/waStore'
import WaStatusBadge from '../../components/wa/StatusBadge'
import ProjectSiteDayTimeline from '../../components/wa/ProjectSiteDayTimeline'
import { MapPin, Layers, HardDrive, ChevronLeft, Folder } from 'lucide-react'
import api from '../../lib/api'
import {
  bucketCodeForProjectsUrl,
  formatWaProjectTitleSuffix,
  inferRangeBucketCode,
  siteNumberFromProject,
  waProjectsListPath,
} from '../../lib/waProjects'

function nasFolderApiParams(searchParams: URLSearchParams): Record<string, string> {
  const out: Record<string, string> = {}
  const fn = searchParams.get('nasFolderName')?.trim()
  const pb = searchParams.get('nasParentBucket')?.trim()
  if (fn) out.nasFolderName = fn
  if (pb) out.nasParentBucket = pb
  return out
}

interface NasFileEntry {
  name: string
  relativePath?: string
  modified?: string
  size?: number
}

interface NasChildFolder {
  folderName: string
  code?: string | null
  isSiteProject?: boolean
}

interface ProjectDetail {
  id?: string
  code: string
  nasFolderName?: string
  nasParentBucket?: string
  location?: string
  stage: string
  status: string
  totalRecords?: number
  nasFileCount?: number
  nasPendingImport?: number
  nasRangeBucket?: boolean
  nasSiteFolderCount?: number
  nasSiteFolders?: { code: string; folderName: string }[]
  nasChildFolders?: NasChildFolder[]
  nasLooseFiles?: NasFileEntry[]
  nasSubfolders?: { name: string }[]
  nasTxtFiles?: NasFileEntry[]
  nasResolvedFolderName?: string
  nasPhysicalFolders?: { folderName: string; nasParentBucket?: string }[]
  nasMountHint?: string
}

function isRangeBucketCode(code: string) {
  return /^PJ-\d+-\d+$/i.test((code || '').trim())
}

/** Enough to render the page when GET /projects/:id times out (NAS or backend queue). */
function detailProjectStub(
  projectId: string,
  nasFolderParams: Record<string, string>,
  projects: { id: string; code: string; stage?: string; status?: string; nasFolderName?: string; nasParentBucket?: string; location?: string }[],
): ProjectDetail | null {
  const hit = projects.find((p) => p.id === projectId)
  if (hit) {
    return {
      ...hit,
      stage: hit.stage || 'active',
      status: hit.status || 'active',
      nasFolderName: nasFolderParams.nasFolderName || hit.nasFolderName,
      nasParentBucket: nasFolderParams.nasParentBucket || hit.nasParentBucket,
    }
  }
  const fn = nasFolderParams.nasFolderName?.trim()
  const pb = nasFolderParams.nasParentBucket?.trim()
  if (!fn && !projectId) return null
  const codeFromFolder = fn?.match(/PJ-\d+/i)?.[0]?.toUpperCase()
  return {
    id: projectId,
    code: codeFromFolder || fn?.slice(0, 24) || projectId.slice(0, 8),
    nasFolderName: fn,
    nasParentBucket: pb,
    stage: 'active',
    status: 'active',
  }
}

function scheduleNasBrowseForProject(
  project: ProjectDetail,
  nasStatusConnected: boolean,
  loadNasBrowse: (
    code: string,
    range: boolean,
    opts?: { subfoldersOnly?: boolean },
  ) => Promise<void>,
) {
  if (!nasStatusConnected || !project.code) return
  const isRange = project.nasRangeBucket ?? isRangeBucketCode(project.code)
  if (isRange) {
    void loadNasBrowse(project.code, true)
    return
  }
  void loadNasBrowse(project.code, false, { subfoldersOnly: true })
}

function NasLooseFileList({ files }: { files: NasFileEntry[] }) {
  return (
    <ul className="max-h-96 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800 rounded-md border border-slate-200 dark:border-slate-700">
      {files.map((f) => (
        <li key={f.relativePath || f.name} className="px-3 py-2 flex justify-between gap-2 text-slate-700 dark:text-slate-300">
          <span className="truncate font-mono text-xs">{f.relativePath || f.name}</span>
          {f.modified && (
            <span className="text-[10px] text-slate-400 shrink-0">{f.modified.slice(0, 10)}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

export default function WaProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const nasFolderParams = useMemo(() => nasFolderApiParams(searchParams), [searchParams])
  const folderQueryKey = `${searchParams.get('nasFolderName') || ''}|${searchParams.get('nasParentBucket') || ''}`
  const { projects, records, fetchProjectRecords, nasStatus, fetchNasStatus } = useWaStore()
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [nasChildFolders, setNasChildFolders] = useState<NasChildFolder[]>([])
  const [nasBrowseSubfolders, setNasBrowseSubfolders] = useState<{ name: string }[]>([])
  const [nasBrowseHint, setNasBrowseHint] = useState<string | null>(null)
  const [nasBrowseLoading, setNasBrowseLoading] = useState(false)
  const [nasImageFiles, setNasImageFiles] = useState<NasFileEntry[]>([])
  const [siteNasLoading, setSiteNasLoading] = useState(false)
  const [projectLoading, setProjectLoading] = useState(true)
  const [recordsLoading, setRecordsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadWarning, setLoadWarning] = useState<string | null>(null)
  const nasSideDataKeyRef = useRef('')

  const isRangeBucket = useMemo(
    () => (project ? (project.nasRangeBucket ?? isRangeBucketCode(project.code)) : false),
    [project],
  )

  const backToProjectsPath = useMemo(() => {
    const pb =
      searchParams.get('nasParentBucket')?.trim()
      || project?.nasParentBucket?.trim()
    let bucketKey = bucketCodeForProjectsUrl(pb, projects)
    if (!bucketKey && project && !isRangeBucketCode(project.code)) {
      const n = siteNumberFromProject(project)
      if (n != null) bucketKey = inferRangeBucketCode(n)
    }
    return waProjectsListPath(bucketKey)
  }, [searchParams, project, projects])

  const loadProjectMinimal = useCallback(
    (projectId: string) =>
      api
        .get(`/wa/projects/${projectId}`, {
          params: { ...nasFolderParams, minimal: '1' },
          timeout: 15000,
        })
        .then(({ data }) => data as ProjectDetail),
    [nasFolderParams],
  )

  const loadNasBrowse = useCallback(
    (code: string, rangeBucket: boolean, opts?: { subfoldersOnly?: boolean }) => {
      if (!nasStatus?.connected) return Promise.resolve()
      setNasBrowseLoading(true)
      setNasBrowseHint(null)
      const params = rangeBucket
        ? { code }
        : {
            code,
            ...nasFolderParams,
            ...(opts?.subfoldersOnly ? { subfoldersOnly: '1' } : {}),
          }
      return api
        .get<{
          childFolders?: NasChildFolder[]
          subfolders?: { name: string }[]
          hint?: string
        }>('/wa/nas/browse', { params, timeout: 45000 })
        .then(({ data }) => {
          if (data.hint?.trim()) setNasBrowseHint(data.hint.trim())
          if (rangeBucket && data.childFolders?.length) {
            setNasChildFolders(data.childFolders)
          }
          if (!rangeBucket && data.subfolders?.length) {
            setNasBrowseSubfolders(data.subfolders)
          }
        })
        .catch(() => {
          setNasBrowseHint('Could not read NAS folders right now. Try again in a moment.')
        })
        .finally(() => {
          setNasBrowseLoading(false)
        })
    },
    [nasFolderParams, nasStatus?.connected],
  )

  const loadProjectSiteNasData = useCallback(
    (projectId: string, code: string) => {
      if (!nasStatus?.connected) return Promise.resolve()
      setSiteNasLoading(true)
      return Promise.all([
        api.get<{ ok?: boolean; files?: NasFileEntry[] }>(`/wa/projects/${projectId}/nas/txt`, {
          params: nasFolderParams,
          timeout: 20000,
        }),
        api.get<{ files?: NasFileEntry[] }>('/wa/nas/browse', {
          params: { code, ...nasFolderParams, filesOnly: '1' },
          timeout: 120000,
        }),
      ])
        .then(([txtRes, browseRes]) => {
          const txt = txtRes.data.files ?? []
          setProject((p) => (p ? { ...p, nasTxtFiles: txt } : p))
          setNasImageFiles(browseRes.data.files ?? [])
        })
        .catch(() => {})
        .finally(() => setSiteNasLoading(false))
    },
    [nasFolderParams, nasStatus?.connected],
  )

  const refreshSiteTimeline = useCallback(() => {
    if (!id || !project?.code) return
    void loadProjectSiteNasData(id, project.code)
    void fetchProjectRecords(id, { limit: '50' })
  }, [id, project?.code, loadProjectSiteNasData, fetchProjectRecords])

  useEffect(() => {
    void fetchNasStatus()
  }, [fetchNasStatus])

  useEffect(() => {
    if (!id) return
    let cancelled = false
    nasSideDataKeyRef.current = ''
    setNasChildFolders([])
    setNasBrowseSubfolders([])
    setNasImageFiles([])
    setNasBrowseHint(null)
    setRecordsLoading(true)
    setLoadError(null)
    setLoadWarning(null)

    const stub = detailProjectStub(id, nasFolderParams, useWaStore.getState().projects)
    if (stub) {
      setProject(stub)
      setProjectLoading(false)
    } else {
      setProject(null)
      setProjectLoading(true)
    }

    void loadProjectMinimal(id)
      .then((data) => {
        if (cancelled) return
        setProject(data)
        setProjectLoading(false)
        setLoadWarning(null)
      })
      .catch(() => {
        if (cancelled) return
        const fallback = detailProjectStub(id, nasFolderParams, useWaStore.getState().projects)
        if (fallback) {
          setProject((prev) => prev ?? fallback)
          setProjectLoading(false)
          setLoadWarning(
            'Project API timed out — showing cached route data. NAS folders and records may still load.',
          )
          return
        }
        setLoadError('Failed to load project')
        setProjectLoading(false)
      })

    void fetchProjectRecords(id, { limit: '50' }).finally(() => {
      if (!cancelled) setRecordsLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [id, folderQueryKey, loadProjectMinimal, fetchProjectRecords])

  useEffect(() => {
    if (!id || !project?.code || !nasStatus?.connected) return
    const sideKey = `${id}|${folderQueryKey}|${project.code}`
    if (nasSideDataKeyRef.current === sideKey) return
    nasSideDataKeyRef.current = sideKey

    scheduleNasBrowseForProject(project, true, loadNasBrowse)

    const isRange = project.nasRangeBucket ?? isRangeBucketCode(project.code)
    if (isRange) return

    void loadProjectSiteNasData(id, project.code)

    return undefined
  }, [
    id,
    folderQueryKey,
    project?.code,
    project?.nasRangeBucket,
    loadNasBrowse,
    loadProjectSiteNasData,
    nasStatus?.connected,
  ])

  useEffect(() => {
    if (!id || !nasStatus?.connected || !project) return
    const sec = nasStatus.autoSyncIntervalSec ?? 60
    const ms = Math.max(30, sec) * 1000
    const timer = window.setInterval(() => {
      fetchProjectRecords(id)
    }, ms)
    return () => window.clearInterval(timer)
  }, [id, nasStatus?.connected, nasStatus?.autoSyncIntervalSec, fetchProjectRecords, project?.code])

  const displaySubfolders = useMemo(() => {
    if (nasBrowseSubfolders.length > 0) return nasBrowseSubfolders
    return project?.nasSubfolders ?? []
  }, [nasBrowseSubfolders, project?.nasSubfolders])

  const displayChildFolders = useMemo(() => {
    if (nasChildFolders.length > 0) return nasChildFolders
    if (project?.nasChildFolders?.length) return project.nasChildFolders
    return (project?.nasSiteFolders ?? []).map((f) => ({
      folderName: f.folderName,
      code: f.code,
      isSiteProject: true,
    }))
  }, [nasChildFolders, project?.nasChildFolders, project?.nasSiteFolders])

  if (projectLoading && !project) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }

  if (loadError || !project) {
    return <div className="text-center py-20 text-slate-500">{loadError || 'Project not found'}</div>
  }

  const showNasSection =
    isRangeBucket ||
    displaySubfolders.length > 0 ||
    !isRangeBucket ||
    (project.nasLooseFiles?.length ?? 0) > 0 ||
    nasBrowseLoading ||
    Boolean(project.nasMountHint || nasBrowseHint || loadWarning)

  const siteFolderCount = displayChildFolders.filter((f) => f.isSiteProject !== false && f.code).length
    || project.nasSiteFolderCount
    || 0

  return (
    <div className="space-y-6">
      <Link
        to={backToProjectsPath}
        className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
      >
        <ChevronLeft className="h-4 w-4" />
        Back to Projects
      </Link>

      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">
              <span className="font-mono text-sign-600 dark:text-sign-400">{project.code}</span>
              {formatWaProjectTitleSuffix(project) && (
                <>
                  <span className="mx-2 text-slate-400">—</span>
                  {formatWaProjectTitleSuffix(project)}
                </>
              )}
            </h1>
            <WaStatusBadge status={project.status} />
          </div>
          <div className="flex items-center gap-3 mt-1 text-sm text-slate-500 dark:text-slate-400">
            {project.location && (
              <span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{project.location}</span>
            )}
            <span className="flex items-center gap-1"><Layers className="h-3.5 w-3.5" />{project.stage}</span>
            <span>
              {project.totalRecords ?? records.length} record
              {(project.totalRecords ?? records.length) !== 1 ? 's' : ''}
            </span>
            {isRangeBucket && siteFolderCount > 0 && (
              <span className="flex items-center gap-1">
                <HardDrive className="h-3.5 w-3.5" />
                {siteFolderCount} site folder{siteFolderCount !== 1 ? 's' : ''} on NAS
              </span>
            )}
            {!isRangeBucket && (project.nasFileCount ?? 0) > 0 && (
              <span className="flex items-center gap-1">
                <HardDrive className="h-3.5 w-3.5" />
                {project.nasFileCount} on NAS
                {(project.nasPendingImport ?? 0) > 0 && (
                  <span className="text-amber-600 dark:text-amber-400">
                    ({project.nasPendingImport} pending import)
                  </span>
                )}
              </span>
            )}
          </div>
        </div>
      </div>

      {showNasSection && (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/40 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center gap-2">
            <HardDrive className="h-4 w-4 text-sign-600 dark:text-sign-400" />
            <h2 className="font-semibold text-slate-900 dark:text-white text-sm">NAS on shared drive</h2>
          </div>
          <div className="p-4 space-y-4 text-sm">
            {(loadWarning || project.nasMountHint || nasBrowseHint) && (
              <p className="text-amber-700 dark:text-amber-400 text-xs">
                {loadWarning || project.nasMountHint || nasBrowseHint}
              </p>
            )}
            {!isRangeBucket && (project.nasResolvedFolderName || project.nasFolderName) && (
              <p className="text-xs text-slate-500 dark:text-slate-400 font-mono break-all">
                NAS folder: {project.nasResolvedFolderName || project.nasFolderName}
              </p>
            )}
            {!isRangeBucket && (project.nasPhysicalFolders?.length ?? 0) > 1 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                  Other folders for this site on the share
                </p>
                <ul className="flex flex-col gap-1">
                  {(project.nasPhysicalFolders ?? []).map((f) => {
                    const active =
                      (project.nasFolderName || '').trim() === (f.folderName || '').trim()
                    const q = new URLSearchParams({
                      nasFolderName: f.folderName,
                      ...(f.nasParentBucket ? { nasParentBucket: f.nasParentBucket } : {}),
                    })
                    return (
                      <li key={f.folderName}>
                        {active ? (
                          <span className="text-sign-600 dark:text-sign-400 text-xs font-mono">{f.folderName}</span>
                        ) : (
                          <Link
                            to={`/wa/projects/${id}?${q.toString()}`}
                            className="text-xs font-mono text-slate-600 hover:text-sign-600 dark:text-slate-400 dark:hover:text-sign-400"
                          >
                            {f.folderName}
                          </Link>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
            {isRangeBucket && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                  Folders in this range bucket
                </p>
                {nasBrowseLoading && displayChildFolders.length === 0 ? (
                  <div className="flex justify-center py-8">
                    <div className="w-6 h-6 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
                  </div>
                ) : displayChildFolders.length === 0 ? (
                  <p className="text-slate-500 text-sm py-4">
                    No folders found. Check NAS mount or restart the backend.
                  </p>
                ) : (
                  <ul className="max-h-80 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800 rounded-md border border-slate-200 dark:border-slate-700">
                    {displayChildFolders.map((f) => (
                      <li key={f.folderName} className="px-3 py-2 flex items-start gap-2">
                        <Folder className="h-4 w-4 text-slate-400 shrink-0 mt-0.5" />
                        <div className="min-w-0 flex-1 flex justify-between gap-2">
                          {f.code ? (
                            <span className="font-mono text-sign-600 dark:text-sign-400 shrink-0">{f.code}</span>
                          ) : (
                            <span className="text-slate-400 shrink-0 text-xs">—</span>
                          )}
                          <span className="text-slate-600 dark:text-slate-400 truncate text-right">{f.folderName}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {!isRangeBucket && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Subfolders</p>
                {nasBrowseLoading && displaySubfolders.length === 0 ? (
                  <div className="flex justify-center py-6">
                    <div className="w-6 h-6 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
                  </div>
                ) : displaySubfolders.length > 0 ? (
                  <ul className="flex flex-wrap gap-2">
                    {displaySubfolders.map((s) => (
                      <li
                        key={s.name}
                        className="px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 flex items-center gap-1"
                      >
                        <Folder className="h-3.5 w-3.5" />
                        {s.name}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-slate-500 text-sm">No subfolders in this NAS directory.</p>
                )}
              </div>
            )}
            {(project.nasLooseFiles?.length ?? 0) > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                  Files on bucket root (not auto-imported)
                </p>
                <NasLooseFileList files={project.nasLooseFiles!} />
              </div>
            )}
          </div>
        </div>
      )}

      {!isRangeBucket && (
        <ProjectSiteDayTimeline
          projectId={id!}
          nasConnected={Boolean(nasStatus?.connected)}
          nasFolderParams={nasFolderParams}
          txtFiles={project.nasTxtFiles ?? []}
          nasImages={nasImageFiles}
          records={records}
          loading={siteNasLoading || recordsLoading}
          onRefresh={refreshSiteTimeline}
        />
      )}

    </div>
  )
}
