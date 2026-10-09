import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useWaStore } from '../../store/waStore'
import { filterWaProjects } from '../../lib/waProjects'
import WaStatusBadge from '../../components/wa/StatusBadge'
import clsx from 'clsx'
import { FolderOpen, ArrowRight, Calendar, Inbox, HardDrive, Search, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'

export default function WaProjectsPage() {
  const { projects, fetchProjects, loading, nasStatus, nasStatusLoading, fetchNasStatus, syncNasFromDrive } = useWaStore()
  const [search, setSearch] = useState('')
  const [syncingNas, setSyncingNas] = useState(false)

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

  const filteredProjects = useMemo(
    () => filterWaProjects(projects, search),
    [projects, search]
  )

  const hasSearch = search.trim().length > 0

  const handleNasSync = async () => {
    setSyncingNas(true)
    try {
      const { created, removed, totalCreated, totalRemoved } = await syncNasFromDrive()
      const parts = []
      if (created.length) parts.push(`${created.length} project(s) created`)
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
          <p className="text-slate-600 dark:text-slate-400 mt-1">
            {hasSearch
              ? `${filteredProjects.length} of ${projects.length} project${projects.length !== 1 ? 's' : ''}`
              : `${projects.length} active project${projects.length !== 1 ? 's' : ''}`}
          </p>
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
            placeholder="Search by code, name, location, status..."
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
                    {nasStatus?.connected ? 'Connected' : 'Disconnected'}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {nasStatus?.watchDir || (nasStatusLoading ? '…' : '—')}
                {!nasStatusLoading && !nasStatus?.connected && nasStatus?.mountHint && (
                  <span className="block mt-1 text-amber-700 dark:text-amber-400">{nasStatus.mountHint}</span>
                )}
                {!nasStatusLoading && nasStatus?.connected && nasStatus.foldersFound > 0 && (
                  <span className="ml-2">· {nasStatus.foldersFound} folder{nasStatus.foldersFound !== 1 ? 's' : ''}</span>
                )}
                {!nasStatusLoading && nasStatus?.connected && (nasStatus.autoSyncIntervalSec ?? 0) > 0 && (
                  <span className="ml-2">· Auto-sync every {nasStatus.autoSyncIntervalSec}s (NAS → web)</span>
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
      ) : filteredProjects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Search className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
          <p className="text-slate-500 dark:text-slate-400">No projects match your search</p>
          <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">Try a different code, name, or location</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredProjects.map((project) => (
            <div key={project.id} className="group card hover:border-slate-400 dark:hover:border-slate-500 transition-colors p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-slate-900 dark:text-white truncate">{project.name}</h3>
                  <p className="text-xs font-mono text-slate-500 dark:text-slate-400 mt-0.5">{project.code}</p>
                </div>
              </div>

              {project.location && (
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-3 truncate">{project.location}</p>
              )}

              <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 mb-4">
                <span className="flex items-center gap-1"><Inbox className="h-3 w-3" />{project.totalRecords ?? 0} records</span>
                {(project.todayRecords ?? 0) > 0 && (
                  <span className="flex items-center gap-1 text-sign-600 dark:text-sign-400 font-medium">
                    <Calendar className="h-3 w-3" />+{project.todayRecords} today
                  </span>
                )}
                {nasStatus?.connected && (project.nasFileCount ?? 0) > 0 && (
                  <span className="flex items-center gap-1 text-amber-700 dark:text-amber-400">
                    <HardDrive className="h-3 w-3" />{project.nasFileCount} on NAS
                  </span>
                )}
              </div>

              <div className="flex items-center justify-between pt-3 border-t border-slate-200 dark:border-slate-700">
                <WaStatusBadge status={project.status} size="sm" />
                <Link to={`/wa/projects/${project.id}`} className="inline-flex items-center gap-1 text-xs font-medium text-sign-600 hover:text-sign-500 dark:text-sign-400">
                  Open <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
