import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useWaStore, type WaProject } from '../../store/waStore'
import {
  buildProjectBuckets,
  bucketSiteProjects,
  bucketFolderLabel,
  filterWaProjects,
  isRangeBucketCode,
  isStandaloneBucketCode,
  projectMatchesQuery,
  standaloneBucketDisplayCode,
  formatWaProjectLabel,
  type WaProjectBucket,
} from '../../lib/waProjects'
import WaStatusBadge from '../../components/wa/StatusBadge'
import clsx from 'clsx'
import {
  FolderOpen,
  Folder,
  ArrowRight,
  Calendar,
  Inbox,
  HardDrive,
  Search,
  RefreshCw,
  ChevronLeft,
} from 'lucide-react'
import toast from 'react-hot-toast'

export default function WaProjectsPage() {
  const {
    projects,
    fetchProjects,
    loading,
    nasStatus,
    nasStatusLoading,
    fetchNasStatus,
    syncNasFromDrive,
    fetchNasBucketSites,
  } = useWaStore()
  const [search, setSearch] = useState('')
  const [selectedBucketCode, setSelectedBucketCode] = useState<string | null>(null)
  const [syncingNas, setSyncingNas] = useState(false)
  const [bucketSyncing, setBucketSyncing] = useState(false)
  const [bucketSites, setBucketSites] = useState<WaProject[]>([])
  /** 'nas' = full shared-drive list; 'mongo' = fallback when NAS API failed */
  const [bucketSitesSource, setBucketSitesSource] = useState<'nas' | 'mongo' | null>(null)
  /** Physical NAS folder count per bucket (from shared drive scan, not MongoDB). */
  const [nasFolderCountsByBucket, setNasFolderCountsByBucket] = useState<Record<string, number>>({})

  useEffect(() => {
    fetchProjects()
    fetchNasStatus()
  }, [fetchProjects, fetchNasStatus])

  useEffect(() => {
    if (!nasStatus?.connected) return
    const sec = nasStatus.autoSyncIntervalSec ?? 60
    const ms = Math.max(30, sec) * 1000
    const timer = window.setInterval(() => {
      fetchProjects()
      fetchNasStatus()
    }, ms)
    return () => window.clearInterval(timer)
  }, [nasStatus?.connected, nasStatus?.autoSyncIntervalSec, fetchProjects, fetchNasStatus])

  useEffect(() => {
    if (!selectedBucketCode || !nasStatus?.connected) {
      setBucketSites([])
      setBucketSitesSource(null)
      return
    }
    const nasBucket = bucketFolderLabel(selectedBucketCode)
    let cancelled = false
    setBucketSyncing(true)
    setBucketSites([])
    setBucketSitesSource(null)
    fetchNasBucketSites(nasBucket)
      .then((sites) => {
        if (cancelled) return
        setBucketSites(sites)
        setBucketSitesSource('nas')
        if (selectedBucketCode) {
          setNasFolderCountsByBucket((prev) => ({
            ...prev,
            [selectedBucketCode]: sites.length,
          }))
        }
        return fetchProjects()
      })
      .catch(() => {
        if (!cancelled) {
          setBucketSitesSource('mongo')
          toast.error('Could not read folders from the shared drive. Showing app projects only — try Sync NAS or refresh.')
        }
      })
      .finally(() => {
        if (!cancelled) setBucketSyncing(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedBucketCode, nasStatus?.connected, fetchNasBucketSites, fetchProjects])

  const buckets = useMemo(() => buildProjectBuckets(projects), [projects])

  const selectedBucket = useMemo(
    () => (selectedBucketCode ? buckets.find((b) => b.code === selectedBucketCode) : null),
    [buckets, selectedBucketCode]
  )

  const filteredBuckets = useMemo(() => {
    const q = search.trim()
    if (!q) return buckets
    return buckets.filter((b) => {
      const displayCode = isStandaloneBucketCode(b.code)
        ? standaloneBucketDisplayCode(b.code)
        : b.code
      const codeMatch =
        displayCode.toLowerCase().includes(q.toLowerCase()) ||
        b.label.toLowerCase().includes(q.toLowerCase())
      return codeMatch || b.siteProjects.some((p) => projectMatchesQuery(p, q))
    })
  }, [buckets, search])

  const filteredSiteProjects = useMemo(() => {
    if (!selectedBucket) return []
    if (bucketSitesSource === 'nas') {
      return filterWaProjects(bucketSites, search)
    }
    if (bucketSitesSource === 'mongo' || bucketSites.length === 0) {
      return filterWaProjects(bucketSiteProjects(selectedBucket), search)
    }
    return filterWaProjects(bucketSites, search)
  }, [selectedBucket, bucketSites, bucketSitesSource, search])

  const hasSearch = search.trim().length > 0
  const atBucketRoot = selectedBucketCode == null

  const subtitle = useMemo(() => {
    if (atBucketRoot) {
      const n = hasSearch ? filteredBuckets.length : buckets.length
      return hasSearch
        ? `${n} of ${buckets.length} folder${buckets.length !== 1 ? 's' : ''}`
        : `${n} NAS folder${n !== 1 ? 's' : ''} · ${projects.filter((p) => !isRangeBucketCode(p.code)).length} site projects`
    }
    const total =
      bucketSitesSource === 'nas'
        ? bucketSites.length
        : selectedBucket
          ? bucketSiteProjects(selectedBucket).length
          : 0
    const n = filteredSiteProjects.length
    const bucketLabel = selectedBucketCode || ''
    return hasSearch
      ? `${n} of ${total} folder${total !== 1 ? 's' : ''} on shared drive in ${bucketLabel}`
      : `${total} folder${total !== 1 ? 's' : ''} on shared drive in ${bucketLabel}`
  }, [
    atBucketRoot,
    bucketSites.length,
    bucketSitesSource,
    buckets.length,
    filteredBuckets.length,
    filteredSiteProjects.length,
    hasSearch,
    projects,
    selectedBucket,
    selectedBucketCode,
  ])

  const handleNasSync = async () => {
    setSyncingNas(true)
    try {
      const { created, removed, foldersCreated, totalCreated, totalRemoved } = await syncNasFromDrive()
      const parts = []
      if (foldersCreated?.length) parts.push(`${foldersCreated.length} folder(s) pushed to NAS`)
      if (created.length) parts.push(`${created.length} project(s) created from NAS`)
      if (removed?.length) parts.push(`${removed.length} project(s) removed (NAS folder deleted)`)
      if (totalCreated) parts.push(`${totalCreated} NAS photo(s) imported`)
      if (totalRemoved) parts.push(`${totalRemoved} record(s) removed (NAS file deleted)`)
      toast.success(parts.length ? parts.join('; ') : 'NAS is already in sync')
      await fetchNasStatus()
    } catch (err: unknown) {
      const ax = err as { response?: { status?: number; data?: { error?: string; message?: string } }; code?: string }
      const msg = ax.response?.data?.error || ax.response?.data?.message
      if (ax.response?.status === 404) {
        toast.error('NAS sync API missing — restart the backend (PORT=5001), then try again.')
      } else if (ax.code === 'ECONNABORTED') {
        toast.error('NAS sync timed out. It may still be running — refresh in a minute.')
      } else if (ax.response?.status === 502 || ax.response?.status === 503) {
        toast.error(msg || 'Backend unavailable during sync. Restart backend and remount NAS if needed.')
      } else {
        toast.error(msg || 'NAS sync failed. Check mount and that backend runs on port 5001.')
      }
    } finally {
      setSyncingNas(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">WA Projects</h1>
          {!atBucketRoot && (
            <button
              type="button"
              onClick={() => setSelectedBucketCode(null)}
              className="mt-2 inline-flex items-center gap-1 text-sm text-sign-600 hover:text-sign-500 dark:text-sign-400"
            >
              <ChevronLeft className="h-4 w-4" />
              All folders
            </button>
          )}
          <p className="text-slate-600 dark:text-slate-400 mt-1">{subtitle}</p>
        </div>
        <Link to="/wa/admin/projects" className="btn btn-primary text-sm px-4 py-2">+ New Project</Link>
      </div>

      <div className="card p-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by code, NAS folder, location, status..."
            className="input pl-9 w-full"
          />
        </div>
      </div>

      {/* NAS Connection Status */}
      {(nasStatusLoading || nasStatus?.enabled) && (
        <div className="card p-4">
          <div className="flex items-center gap-3">
            <div className={clsx(
              'p-2 rounded-lg',
              nasStatus?.connected ? 'bg-sign-100 dark:bg-sign-900/30' : 'bg-slate-100 dark:bg-slate-800'
            )}>
              <HardDrive className={clsx(
                'h-5 w-5',
                nasStatus?.connected ? 'text-sign-600 dark:text-sign-400' : 'text-slate-400'
              )} />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h2 className="font-semibold text-slate-900 dark:text-white text-sm">NAS Shared Drive</h2>
                {nasStatusLoading ? (
                  <span className="text-xs text-slate-500">Checking…</span>
                ) : (
                  <span className={clsx(
                    'inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full',
                    nasStatus?.connected
                      ? 'bg-sign-100 text-sign-700 dark:bg-sign-900/30 dark:text-sign-400'
                      : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                  )}>
                    <span className={clsx(
                      'inline-block h-1.5 w-1.5 rounded-full',
                      nasStatus?.connected ? 'bg-sign-500' : 'bg-slate-400'
                    )} />
                    {nasStatus?.connected
                      ? (nasStatus.degraded ? 'Connected (slow)' : 'Connected')
                      : 'Disconnected'}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {nasStatus?.watchDir || (nasStatusLoading ? '…' : '—')}
                {!nasStatusLoading && !nasStatus?.connected && nasStatus?.mountHint && (
                  <span className="block mt-1 text-amber-700 dark:text-amber-400">{nasStatus.mountHint}</span>
                )}
                {!nasStatusLoading && nasStatus?.connected && nasStatus.degraded && nasStatus?.mountHint && (
                  <span className="block mt-1 text-amber-700 dark:text-amber-400">{nasStatus.mountHint}</span>
                )}
                {!nasStatusLoading && nasStatus?.connected && nasStatus.foldersFound > 0 && (
                  <span className="ml-2">· {nasStatus.foldersFound} folder{nasStatus.foldersFound !== 1 ? 's' : ''}</span>
                )}
                {!nasStatusLoading && nasStatus?.connected && (nasStatus.autoSyncIntervalSec ?? 0) > 0 && (
                  <span className="ml-2">· Auto-sync every {nasStatus.autoSyncIntervalSec}s (NAS ↔ web)</span>
                )}
              </p>
            </div>
            {!nasStatusLoading && nasStatus?.connected && (
              <button
                type="button"
                onClick={handleNasSync}
                disabled={syncingNas}
                className="btn btn-secondary text-xs px-3 py-1.5 inline-flex items-center gap-1.5"
              >
                <RefreshCw className={clsx('h-3.5 w-3.5', syncingNas && 'animate-spin')} />
                {syncingNas ? 'Syncing…' : 'Sync NAS'}
              </button>
            )}
          </div>
        </div>
      )}

      {loading && projects.length === 0 ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <FolderOpen className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
          <p className="text-slate-500 dark:text-slate-400">No projects yet</p>
          <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">Create your first project to get started</p>
        </div>
      ) : atBucketRoot && filteredBuckets.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Search className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
          <p className="text-slate-500 dark:text-slate-400">No folders match your search</p>
          <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">Try a different code or project name</p>
        </div>
      ) : !atBucketRoot && bucketSyncing && bucketSitesSource !== 'nas' ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-500">
          <RefreshCw className="h-10 w-10 animate-spin text-sign-500 mb-3" />
          <p>Loading folders from shared drive: {bucketFolderLabel(selectedBucketCode!)}…</p>
        </div>
      ) : !atBucketRoot && filteredSiteProjects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          {hasSearch ? (
            <>
              <Search className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
              <p className="text-slate-500 dark:text-slate-400">No projects match your search</p>
              <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">Try a different code, folder, or location</p>
            </>
          ) : (
            <>
              <FolderOpen className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
              <p className="text-slate-500 dark:text-slate-400">No site projects in this folder yet</p>
              <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">Sync NAS or create a project under {selectedBucketCode}</p>
            </>
          )}
        </div>
      ) : atBucketRoot ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredBuckets.map((bucket) => (
            <BucketCard
              key={bucket.code}
              bucket={bucket}
              nasFolderCount={nasFolderCountsByBucket[bucket.code]}
              onOpen={() => setSelectedBucketCode(bucket.code)}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          {bucketSitesSource === 'mongo' && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
              Shared drive folder list unavailable — showing app projects only. Use Sync NAS or refresh this page.
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredSiteProjects.map((project) => (
              <SiteProjectCard
                key={project.nasFolderName || project.id}
                project={project}
                nasConnected={!!nasStatus?.connected}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function BucketCard({
  bucket,
  nasFolderCount,
  onOpen,
}: {
  bucket: WaProjectBucket
  nasFolderCount?: number
  onOpen: () => void
}) {
  const mongoCount = bucketSiteProjects(bucket).length
  const count = nasFolderCount ?? mongoCount
  const countHint =
    nasFolderCount != null && nasFolderCount !== mongoCount
      ? `${nasFolderCount} on shared drive · ${mongoCount} in app`
      : `${count} folder${count !== 1 ? 's' : ''} on shared drive`
  const isRange = isRangeBucketCode(bucket.code)
  const title = isRange
    ? bucket.code
    : isStandaloneBucketCode(bucket.code)
      ? standaloneBucketDisplayCode(bucket.code)
      : bucket.code

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group card hover:border-sign-400 dark:hover:border-sign-600 transition-colors p-5 text-left w-full"
    >
      <div className="flex items-start gap-3 mb-3">
        <div className="p-2 rounded-lg bg-sign-100 dark:bg-sign-900/30 shrink-0">
          <Folder className="h-5 w-5 text-sign-600 dark:text-sign-400" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-slate-900 dark:text-white truncate font-mono">{title}</h3>
          {bucket.label !== title && (
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 truncate">{bucket.label}</p>
          )}
        </div>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">{countHint}</p>
      <div className="flex items-center justify-between pt-3 border-t border-slate-200 dark:border-slate-700">
        {bucket.projectId ? (
          <Link
            to={`/wa/projects/${bucket.projectId}`}
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-slate-500 hover:text-sign-600 dark:hover:text-sign-400"
          >
            NAS folder details
          </Link>
        ) : (
          <span className="text-xs text-slate-400">{isRange ? 'Range folder' : 'NAS folder'}</span>
        )}
        <span className="inline-flex items-center gap-1 text-xs font-medium text-sign-600 group-hover:text-sign-500 dark:text-sign-400">
          Open folder <ArrowRight className="h-3 w-3" />
        </span>
      </div>
    </button>
  )
}

function SiteProjectCard({
  project,
  nasConnected,
}: {
  project: WaProject
  nasConnected: boolean
}) {
  return (
    <div className="group card hover:border-slate-400 dark:hover:border-slate-500 transition-colors p-5">
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-slate-900 dark:text-white text-sm leading-snug break-words whitespace-normal">
            {formatWaProjectLabel(project)}
          </h3>
          {formatWaProjectLabel(project).toUpperCase() !== (project.code || '').toUpperCase() && (
            <p className="text-xs font-mono text-slate-500 dark:text-slate-400 mt-1">{project.code}</p>
          )}
        </div>
      </div>

      {project.location && (
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-3 truncate">{project.location}</p>
      )}

      <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 mb-4">
        <span className="flex items-center gap-1">
          <Inbox className="h-3 w-3" />
          {project.totalRecords ?? 0} records
        </span>
        {(project.todayRecords ?? 0) > 0 && (
          <span className="flex items-center gap-1 text-sign-600 dark:text-sign-400 font-medium">
            <Calendar className="h-3 w-3" />+{project.todayRecords} today
          </span>
        )}
        {nasConnected && (project.nasFileCount ?? 0) > 0 && (
          <span className="flex items-center gap-1 text-amber-700 dark:text-amber-400">
            <HardDrive className="h-3 w-3" />
            {project.nasFileCount} on NAS
          </span>
        )}
      </div>

      <div className="flex items-center justify-between pt-3 border-t border-slate-200 dark:border-slate-700">
        <WaStatusBadge status={project.status} size="sm" />
        {project.id.startsWith('nas:') ? (
          <span className="text-xs text-slate-400">Shared drive only</span>
        ) : (
          <Link
            to={{
              pathname: `/wa/projects/${project.id}`,
              search: project.nasFolderName
                ? new URLSearchParams({
                    nasFolderName: project.nasFolderName,
                    ...(project.nasParentBucket
                      ? { nasParentBucket: project.nasParentBucket }
                      : {}),
                  }).toString()
                : '',
            }}
            className="inline-flex items-center gap-1 text-xs font-medium text-sign-600 hover:text-sign-500 dark:text-sign-400"
          >
            Open <ArrowRight className="h-3 w-3" />
          </Link>
        )}
      </div>
    </div>
  )
}
