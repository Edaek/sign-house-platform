import { useEffect, useState, useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useWaStore } from '../../store/waStore'
import WaStatusBadge from '../../components/wa/StatusBadge'
import WaRecordTable from '../../components/wa/RecordTable'
import { MapPin, Layers, HardDrive, ChevronLeft, Folder } from 'lucide-react'
import api from '../../lib/api'
import { formatWaProjectLabel } from '../../lib/waProjects'

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
  nasFiles?: NasFileEntry[]
}

function isRangeBucketCode(code: string) {
  return /^PJ-\d+-\d+$/i.test((code || '').trim())
}

function NasFileList({ files }: { files: NasFileEntry[] }) {
  return (
    <ul className="max-h-48 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800 rounded-md border border-slate-200 dark:border-slate-700">
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
  const { records, fetchProjectRecords, nasStatus, fetchNasStatus } = useWaStore()
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [nasChildFolders, setNasChildFolders] = useState<NasChildFolder[]>([])
  const [nasBrowseLoading, setNasBrowseLoading] = useState(false)
  const [projectLoading, setProjectLoading] = useState(true)
  const [recordsLoading, setRecordsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const isRangeBucket = useMemo(
    () => (project ? (project.nasRangeBucket ?? isRangeBucketCode(project.code)) : false),
    [project],
  )

  const loadProject = (projectId: string, codeHint?: string) => {
    const range = codeHint ? isRangeBucketCode(codeHint) : false
    return api
      .get(`/wa/projects/${projectId}`, {
        params: range ? {} : { includeNasFiles: '1' },
      })
      .then(({ data }) => {
        setProject(data)
        const isRange = data.nasRangeBucket ?? isRangeBucketCode(data.code)
        if (isRange && (data.nasChildFolders?.length ?? 0) > 0) {
          setNasChildFolders(data.nasChildFolders!)
        }
        return data as ProjectDetail
      })
  }

  const loadNasBrowse = (code: string) => {
    if (!isRangeBucketCode(code) || !nasStatus?.connected) return Promise.resolve()
    setNasBrowseLoading(true)
    return api
      .get('/wa/nas/browse', { params: { code } })
      .then(({ data }) => {
        if (data.childFolders?.length) {
          setNasChildFolders(data.childFolders)
        }
      })
      .catch(() => {})
      .finally(() => setNasBrowseLoading(false))
  }

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setProject(null)
    setNasChildFolders([])
    setProjectLoading(true)
    setRecordsLoading(true)
    setLoadError(null)

    loadProject(id)
      .then((data) => {
        if (cancelled) return
        const isRange = data.nasRangeBucket ?? isRangeBucketCode(data.code)
        if (isRange && !(data.nasChildFolders?.length ?? 0)) {
          return loadNasBrowse(data.code)
        }
      })
      .catch(() => {
        if (!cancelled) setLoadError('Failed to load project')
      })
      .finally(() => {
        if (!cancelled) setProjectLoading(false)
      })

    fetchProjectRecords(id).finally(() => {
      if (!cancelled) setRecordsLoading(false)
    })

    fetchNasStatus()

    return () => {
      cancelled = true
    }
  }, [id, fetchProjectRecords, fetchNasStatus])

  useEffect(() => {
    if (!id || !project || !nasStatus?.connected) return
    const isRange = project.nasRangeBucket ?? isRangeBucketCode(project.code)
    if (isRange && nasChildFolders.length === 0) {
      loadNasBrowse(project.code)
    }
  }, [id, project?.code, nasStatus?.connected])

  useEffect(() => {
    if (!id || !nasStatus?.connected || !project) return
    const sec = nasStatus.autoSyncIntervalSec ?? 60
    const ms = Math.max(30, sec) * 1000
    const timer = window.setInterval(() => {
      loadProject(id, project.code).catch(() => {})
      fetchProjectRecords(id)
    }, ms)
    return () => window.clearInterval(timer)
  }, [id, nasStatus?.connected, nasStatus?.autoSyncIntervalSec, fetchProjectRecords, project?.code])

  const displayChildFolders = useMemo(() => {
    if (nasChildFolders.length > 0) return nasChildFolders
    if (project?.nasChildFolders?.length) return project.nasChildFolders
    return (project?.nasSiteFolders ?? []).map((f) => ({
      folderName: f.folderName,
      code: f.code,
      isSiteProject: true,
    }))
  }, [nasChildFolders, project?.nasChildFolders, project?.nasSiteFolders])

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }

  if (loadError || !project) {
    return <div className="text-center py-20 text-slate-500">{loadError || 'Project not found'}</div>
  }

  const siteFolderCount = displayChildFolders.filter((f) => f.isSiteProject !== false && f.code).length
    || project.nasSiteFolderCount
    || 0

  return (
    <div className="space-y-6">
      <Link
        to="/wa/projects"
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
              {formatWaProjectLabel(project).toUpperCase() !== project.code.toUpperCase() && (
                <>
                  <span className="mx-2 text-slate-400">—</span>
                  {formatWaProjectLabel(project)}
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

      {(isRangeBucket || (project.nasSubfolders?.length ?? 0) > 0 ||
        (!isRangeBucket && (project.nasFiles?.length ?? 0) > 0) ||
        (project.nasLooseFiles?.length ?? 0) > 0) && (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/40 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center gap-2">
            <HardDrive className="h-4 w-4 text-sign-600 dark:text-sign-400" />
            <h2 className="font-semibold text-slate-900 dark:text-white text-sm">NAS on shared drive</h2>
          </div>
          <div className="p-4 space-y-4 text-sm">
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
            {!isRangeBucket && (project.nasSubfolders?.length ?? 0) > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Subfolders</p>
                <ul className="flex flex-wrap gap-2">
                  {project.nasSubfolders!.map((s) => (
                    <li
                      key={s.name}
                      className="px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 flex items-center gap-1"
                    >
                      <Folder className="h-3.5 w-3.5" />
                      {s.name}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(project.nasLooseFiles?.length ?? 0) > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                  Files on bucket root (not auto-imported)
                </p>
                <NasFileList files={project.nasLooseFiles!} />
              </div>
            )}
            {!isRangeBucket && (project.nasFiles?.length ?? 0) > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Image files</p>
                <NasFileList files={project.nasFiles!} />
              </div>
            )}
          </div>
        </div>
      )}

      {recordsLoading ? (
        <div className="flex items-center justify-center py-16 rounded-lg border border-slate-200 dark:border-slate-700">
          <div className="w-7 h-7 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : (
        <WaRecordTable records={records} />
      )}
    </div>
  )
}
