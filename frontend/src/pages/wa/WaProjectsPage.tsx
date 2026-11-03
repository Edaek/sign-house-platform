import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useWaStore, type WaProject } from '../../store/waStore'
import {
  buildProjectBuckets,
  mergeProjectsWithNasRootBuckets,
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

function NasFolderLoadProgress() {
  return (
    <div className="rounded-lg border border-sign-500/25 bg-sign-500/5 px-4 py-3 space-y-2.5">
      <p className="text-sm font-medium text-sign-900 dark:text-sign-100">
        Loading full folder list from shared drive…
      </p>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-slate-200/90 dark:bg-slate-700"
        role="progressbar"
        aria-valuetext="Loading NAS folders"
      >
        <div className="nas-folder-indeterminate-bar h-full w-1/3 rounded-full bg-sign-500" />
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        App projects are shown below. Folder names will refresh when the NAS scan finishes (may take several minutes on a
        slow connection).
      </p>
    </div>
  )
}

/** Warnings only — loading state uses NasFolderLoadProgress instead. */
function englishBucketWarningHint(h: string | null | undefined): string | null {
  if (!h?.trim()) return null
  const t = h.trim()
  if (/加载|刷新完整|正在从共享|已显示应用/.test(t)) return null
  if (t.includes('暂不可用') || t.includes('未能列出')) {
    return 'Shared drive list unavailable — showing app projects only. Try Sync NAS or refresh.'
  }
  if (t.includes('缓存') || t.includes('stale') || t.includes('cached')) {
    return 'Showing cached folder list. Use Sync NAS to refresh from the share.'
  }
  return t
}

export default function WaProjectsPage() {
  const {
    projects,
    fetchProjects,
    loading,
    nasStatus,
    nasStatusLoading,
    fetchNasStatus,
    syncNasFromDrive,
    syncNasBucket,
    linkNasBucketFolder,
    fetchNasBucketSites,
    fetchNasRootBuckets,
  } = useWaStore()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedBucketCode = useMemo(() => {
    const raw = searchParams.get('bucket')?.trim()
    return raw || null
  }, [searchParams])

  const setSelectedBucketCode = (code: string | null) => {
    const next = new URLSearchParams(searchParams)
    if (code?.trim()) {
      next.set('bucket', code.trim())
    } else {
      next.delete('bucket')
    }
    setSearchParams(next, { replace: !code })
  }

  const [search, setSearch] = useState('')
  const [linkingNasFolder, setLinkingNasFolder] = useState<string | null>(null)
  const [syncingNas, setSyncingNas] = useState(false)
  const [bucketSyncing, setBucketSyncing] = useState(false)
  const [bucketSites, setBucketSites] = useState<WaProject[]>([])
  /** 'nas' = shared-drive list; 'mongo' = fallback when NAS API failed; 'cache' = stale NAS cache */
  const [bucketSitesSource, setBucketSitesSource] = useState<'nas' | 'mongo' | 'cache' | null>(null)
  const [bucketSitesHint, setBucketSitesHint] = useState<string | null>(null)
  /** Physical NAS folder count per bucket (from shared drive scan, not MongoDB). */
  const [nasFolderCountsByBucket, setNasFolderCountsByBucket] = useState<Record<string, number>>({})
  const [nasRootBuckets, setNasRootBuckets] = useState<
    Array<{ bucketCode: string; nasName: string; childCount?: number }>
  >([])

  useEffect(() => {
    fetchProjects()
    fetchNasStatus()
  }, [fetchProjects, fetchNasStatus])

  useEffect(() => {
    if (!nasStatus?.connected) {
      setNasRootBuckets([])
      return
    }
    let cancelled = false
    fetchNasRootBuckets().then((rows) => {
      if (!cancelled) setNasRootBuckets(rows)
    })
    return () => {
      cancelled = true
    }
  }, [nasStatus?.connected, fetchNasRootBuckets, projects.length, syncingNas])

  useEffect(() => {
    if (!nasStatus?.connected) return
    const sec = nasStatus.autoSyncIntervalSec ?? 60
    const ms = Math.max(30, sec) * 1000
    const timer = window.setInterval(() => {
      fetchProjects()
      fetchNasStatus()
      fetchNasRootBuckets().then(setNasRootBuckets)
    }, ms)
    return () => window.clearInterval(timer)
  }, [
    nasStatus?.connected,
    nasStatus?.autoSyncIntervalSec,
    fetchProjects,
    fetchNasStatus,
    fetchNasRootBuckets,
  ])

  useEffect(() => {
    if (!selectedBucketCode || !nasStatus?.connected) {
      setBucketSites([])
      setBucketSitesSource(null)
      setBucketSitesHint(null)
      return
    }
    const nasBucket = selectedBucketCode
    let cancelled = false
    let sitesShown = 0
    const applySites = (sites: WaProject[], staleFromCache: boolean, hint?: string) => {
      if (cancelled) return
      sitesShown = Math.max(sitesShown, sites.length)
      setBucketSites(sites)
      setBucketSitesSource(staleFromCache ? 'cache' : 'nas')
      setBucketSitesHint(hint?.trim() || null)
      if (selectedBucketCode) {
        setNasFolderCountsByBucket((prev) => ({
          ...prev,
          [selectedBucketCode]: sites.length,
        }))
      }
    }

    const localBucket = buildProjectBuckets(useWaStore.getState().projects).find(
      (b) => b.code === selectedBucketCode,
    )
    const localSites = localBucket ? bucketSiteProjects(localBucket) : []

    if (localSites.length > 0) {
      applySites(localSites, true)
    } else {
      setBucketSites([])
      setBucketSitesSource(null)
      setBucketSitesHint(null)
    }
    setBucketSyncing(localSites.length === 0)

    fetchNasBucketSites(nasBucket, { liveScan: true, timeoutMs: 120000 })
      .then(({ sites, staleFromCache, hint }) => {
        if (cancelled) return
        applySites(sites, staleFromCache ?? false, hint)
        setBucketSitesSource(staleFromCache ? 'cache' : 'nas')
        return fetchProjects()
      })
      .catch(() => {
        if (cancelled || sitesShown > 0) return
        if (localSites.length > 0) {
          applySites(
            localSites,
            true,
            'Shared drive list unavailable — showing app projects only.',
          )
          return
        }
        setBucketSitesSource('mongo')
      })
      .finally(() => {
        if (!cancelled) setBucketSyncing(false)
      })

    const poll = window.setInterval(() => {
      fetchNasBucketSites(nasBucket, { liveScan: true, timeoutMs: 120000 })
        .then(({ sites, staleFromCache }) => {
          if (cancelled) return
          applySites(sites, staleFromCache ?? false)
          if (!staleFromCache) setBucketSitesSource('nas')
        })
        .catch(() => {})
    }, 90000)

    return () => {
      cancelled = true
      window.clearInterval(poll)
    }
  }, [selectedBucketCode, nasStatus?.connected, fetchNasBucketSites, fetchProjects])

  const refreshCurrentBucketFromNas = useCallback(async () => {
    if (!selectedBucketCode) return
    setBucketSyncing(true)
    try {
      await syncNasBucket(selectedBucketCode)
      await fetchProjects()
      const { sites, staleFromCache, hint } = await fetchNasBucketSites(selectedBucketCode, {
        liveScan: true,
        timeoutMs: 120000,
      })
      setBucketSites(sites)
      setBucketSitesSource(staleFromCache ? 'cache' : 'nas')
      setBucketSitesHint(hint?.trim() || null)
      setNasFolderCountsByBucket((prev) => ({
        ...prev,
        [selectedBucketCode]: sites.length,
      }))
    } finally {
      setBucketSyncing(false)
    }
  }, [selectedBucketCode, syncNasBucket, fetchProjects, fetchNasBucketSites])

  const handleLinkNasOnlyFolder = useCallback(
    async (row: WaProject) => {
      if (!selectedBucketCode) return
      const folderKey = (row.nasFolderName || row.code || '').trim()
      if (!folderKey) return
      setLinkingNasFolder(folderKey)
      try {
        const { projectId } = await linkNasBucketFolder(selectedBucketCode, folderKey)
        await fetchProjects()
        const { sites, staleFromCache, hint } = await fetchNasBucketSites(selectedBucketCode, {
          liveScan: true,
          timeoutMs: 120000,
        })
        setBucketSites(sites)
        setBucketSitesSource(staleFromCache ? 'cache' : 'nas')
        setBucketSitesHint(hint?.trim() || null)
        const linked =
          sites.find(
            (s) =>
              s.id === projectId ||
              (!s.id.startsWith('nas:') &&
                ((s.nasFolderName || '').toUpperCase() === folderKey.toUpperCase() ||
                  (s.code || '').toUpperCase() === folderKey.toUpperCase())),
          ) ?? null
        if (linked && !linked.id.startsWith('nas:')) {
          toast.success('Folder linked — click Open to enter the project.')
          return
        }
        toast.success('Folder linked — refresh if Open does not appear yet.')
      } catch (err: unknown) {
        const ax = err as { response?: { data?: { error?: string } }; message?: string }
        toast.error(
          ax.response?.data?.error ||
            ax.message ||
            'Could not link this folder. Try Manage Projects: parent bucket KTEST, code KTEST1.',
        )
      } finally {
        setLinkingNasFolder(null)
      }
    },
    [selectedBucketCode, linkNasBucketFolder, fetchProjects, fetchNasBucketSites],
  )

  const buckets = useMemo(
    () => mergeProjectsWithNasRootBuckets(projects, nasRootBuckets).buckets,
    [projects, nasRootBuckets],
  )

  useEffect(() => {
    const { nasFolderCounts } = mergeProjectsWithNasRootBuckets(projects, nasRootBuckets)
    if (Object.keys(nasFolderCounts).length === 0) return
    setNasFolderCountsByBucket((prev) => ({ ...prev, ...nasFolderCounts }))
  }, [projects, nasRootBuckets])

  useEffect(() => {
    if (!selectedBucketCode || loading || projects.length === 0) return
    const ok = buckets.some((b) => b.code === selectedBucketCode)
    if (!ok) {
      const next = new URLSearchParams(searchParams)
      next.delete('bucket')
      setSearchParams(next, { replace: true })
    }
  }, [selectedBucketCode, buckets, loading, projects.length, searchParams, setSearchParams])

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
    if (bucketSites.length > 0) {
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
    const mongoOnly = bucketSitesSource === 'mongo'
    const loadingBucket = !atBucketRoot && bucketSyncing && bucketSites.length === 0
    const total =
      bucketSitesSource === 'nas' || bucketSitesSource === 'cache'
        ? bucketSites.length
        : selectedBucket
          ? bucketSiteProjects(selectedBucket).length
          : 0
    const n = filteredSiteProjects.length
    const bucketLabel = selectedBucketCode || ''
    if (loadingBucket) {
      return `Loading folders from shared drive in ${bucketLabel}…`
    }
    const scope = mongoOnly
      ? `app project${total !== 1 ? 's' : ''} in ${bucketLabel} (shared drive list unavailable)`
      : `${total} folder${total !== 1 ? 's' : ''} on shared drive in ${bucketLabel}`
    return hasSearch
      ? `${n} of ${total} ${mongoOnly ? 'app project' : 'folder'}${total !== 1 ? 's' : ''} in ${bucketLabel}`
      : scope
  }, [
    atBucketRoot,
    bucketSites.length,
    bucketSitesSource,
    bucketSyncing,
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
      const {
        created,
        removed,
        foldersCreated,
        totalCreated,
        totalRemoved,
        skipped,
        skipReason,
      } = await syncNasFromDrive()
      if (skipped) {
        toast('Another NAS sync is still running — wait a moment, then refresh this page.')
        if (selectedBucketCode) await refreshCurrentBucketFromNas()
        return
      }
      const parts = []
      if (foldersCreated?.length) parts.push(`${foldersCreated.length} folder(s) pushed to NAS`)
      if (created.length) parts.push(`${created.length} project(s) created from NAS`)
      if (removed?.length) parts.push(`${removed.length} project(s) removed (NAS folder deleted)`)
      if (totalCreated) parts.push(`${totalCreated} NAS photo(s) imported`)
      if (totalRemoved) parts.push(`${totalRemoved} record(s) removed (NAS file deleted)`)
      toast.success(parts.length ? parts.join('; ') : 'NAS sync finished')
      await fetchNasStatus()
      if (selectedBucketCode) {
        await refreshCurrentBucketFromNas()
      } else {
        const roots = await fetchNasRootBuckets()
        setNasRootBuckets(roots)
      }
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
      ) : !atBucketRoot && bucketSyncing && bucketSites.length === 0 ? (
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
          {bucketSyncing && <NasFolderLoadProgress />}
          {(() => {
            const warning = englishBucketWarningHint(bucketSitesHint)
            if (warning) {
              return (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                  {warning}
                </div>
              )
            }
            if (bucketSitesSource === 'mongo' && bucketSites.length === 0) {
              return (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                  Shared drive folder list unavailable — showing app projects only. Use Sync NAS or refresh this page.
                </div>
              )
            }
            return null
          })()}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredSiteProjects.map((project) => (
              <SiteProjectCard
                key={project.nasFolderName || project.id}
                project={project}
                nasConnected={!!nasStatus?.connected}
                linkingNas={
                  linkingNasFolder !== null &&
                  linkingNasFolder.toUpperCase() ===
                    (project.nasFolderName || project.code || '').toUpperCase()
                }
                onLinkNasFolder={() => handleLinkNasOnlyFolder(project)}
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
  linkingNas,
  onLinkNasFolder,
}: {
  project: WaProject
  nasConnected: boolean
  linkingNas?: boolean
  onLinkNasFolder?: () => void
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
          <button
            type="button"
            disabled={linkingNas}
            onClick={onLinkNasFolder}
            className="inline-flex items-center gap-1 text-xs font-medium text-sign-600 hover:text-sign-500 dark:text-sign-400 disabled:opacity-50"
          >
            {linkingNas ? 'Linking…' : 'Link in app'}
            {!linkingNas && <ArrowRight className="h-3 w-3" />}
          </button>
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
