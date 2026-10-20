import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useWaStore } from '../../store/waStore'
import {
  buildProjectBuckets,
  bucketAdminProject,
  bucketSiteProjects,
  filterWaProjects,
  isNasBucketFolderCode,
  isRangeBucketCode,
  isStandaloneBucketCode,
  mergeNasRootBuckets,
  projectMatchesQuery,
  standaloneBucketDisplayCode,
  parentBucketCodeForNas,
  bucketFolderLabel,
  type WaProjectBucket,
} from '../../lib/waProjects'
import WaStatusBadge from '../../components/wa/StatusBadge'
import toast from 'react-hot-toast'
import {
  Plus,
  FolderOpen,
  Folder,
  Trash2,
  Search,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Pencil,
} from 'lucide-react'
import type { WaProject } from '../../store/waStore'

export default function WaManageProjectsPage() {
  const {
    projects,
    fetchProjects,
    createProject,
    updateProject,
    deleteProject,
    deleteNasRootFolder,
    nasStatus,
    fetchNasStatus,
    syncNasFromDrive,
  } = useWaStore()
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedBucketCode, setSelectedBucketCode] = useState<string | null>(null)
  const [stageFilter, setStageFilter] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; code: string } | null>(null)
  const [deleteNasOnlyFolder, setDeleteNasOnlyFolder] = useState<string | null>(null)

  const [deleteNasFolder, setDeleteNasFolder] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [editTarget, setEditTarget] = useState<WaProject | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [savingEdit, setSavingEdit] = useState(false)
  const [editSyncNas, setEditSyncNas] = useState(true)
  const [editNasFolderName, setEditNasFolderName] = useState('')

  useEffect(() => {
    fetchProjects().then(() => setLoading(false))
    fetchNasStatus()
  }, [fetchProjects, fetchNasStatus])

  const buckets = useMemo(() => {
    const built = buildProjectBuckets(projects)
    const roots = nasStatus?.rootFolderNames
    let list = roots?.length ? mergeNasRootBuckets(built, roots) : built
    if (nasStatus?.connected && roots?.length) {
      const rootSet = new Set(roots.map((n) => n.toUpperCase()))
      list = list.filter((b) => {
        const folder = bucketNasFolderName(b).toUpperCase()
        if (rootSet.has(folder)) return true
        if (b.projectId && bucketAdminProject(b, projects)) return true
        if (isRangeBucketCode(b.code) && b.siteProjects.length > 0) return true
        return false
      })
    }
    return list
  }, [projects, nasStatus?.connected, nasStatus?.rootFolderNames])

  const selectedBucket = useMemo(
    () => (selectedBucketCode ? buckets.find((b) => b.code === selectedBucketCode) : null),
    [buckets, selectedBucketCode]
  )

  const bucketMatchesStage = (bucket: WaProjectBucket) => {
    if (!stageFilter) return true
    if (bucket.projectId) {
      const rangeProj = projects.find((p) => p.id === bucket.projectId)
      if (rangeProj?.stage === stageFilter) return true
    }
    return bucket.siteProjects.some((p) => p.stage === stageFilter)
  }

  const filteredBuckets = useMemo(() => {
    const q = search.trim()
    return buckets.filter((bucket) => {
      if (!bucketMatchesStage(bucket)) return false
      if (!q) return true
      const displayCode = isStandaloneBucketCode(bucket.code)
        ? standaloneBucketDisplayCode(bucket.code)
        : bucket.code
      const codeMatch =
        displayCode.toLowerCase().includes(q.toLowerCase()) ||
        bucket.label.toLowerCase().includes(q.toLowerCase())
      return codeMatch || bucket.siteProjects.some((p) => projectMatchesQuery(p, q))
    })
  }, [buckets, search, stageFilter, projects])

  const filteredSiteProjects = useMemo(() => {
    if (!selectedBucket) return []
    const sites = bucketSiteProjects(selectedBucket)
    return filterWaProjects(sites, search, stageFilter || undefined)
  }, [selectedBucket, search, stageFilter])

  const atBucketRoot = selectedBucketCode == null
  const hasFilters = search.trim().length > 0 || stageFilter.length > 0

  const subtitle = useMemo(() => {
    if (atBucketRoot) {
      const n = hasFilters ? filteredBuckets.length : buckets.length
      return hasFilters
        ? `${n} of ${buckets.length} folders`
        : `${n} NAS folders · ${projects.filter((p) => !isRangeBucketCode(p.code)).length} site projects`
    }
    const total = selectedBucket ? bucketSiteProjects(selectedBucket).length : 0
    const n = filteredSiteProjects.length
    const folderLabel = selectedBucketCode ? bucketFolderLabel(selectedBucketCode) : ''
    return hasFilters ? `${n} of ${total} projects in ${folderLabel}` : `${total} projects in ${folderLabel}`
  }, [
    atBucketRoot,
    buckets.length,
    filteredBuckets.length,
    filteredSiteProjects.length,
    hasFilters,
    projects,
    selectedBucket,
    selectedBucketCode,
  ])

  const createParentFolder = selectedBucketCode ? parentBucketCodeForNas(selectedBucketCode) : undefined

  async function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (creating) return
    setCreateError(null)
    setCreating(true)
    const form = new FormData(e.currentTarget)
    try {
      await createProject({
        code: form.get('code') as string,
        location: (form.get('location') as string) || undefined,
        stage: form.get('stage') as string,
        ...(createParentFolder ? { parentBucketCode: createParentFolder } : {}),
      })
      await fetchProjects()
      setDialogOpen(false)
      toast.success(
        createParentFolder && nasStatus?.connected
          ? 'Project created on web and NAS folder synced'
          : 'Project created'
      )
      if (nasStatus?.connected) {
        void syncNasFromDrive()
          .then(() => fetchProjects())
          .catch(() => {})
        fetchNasStatus()
      }
    } catch (err: unknown) {
      const ax = err as {
        response?: { status?: number; data?: { error?: string; message?: string; msg?: string } }
      }
      const data = ax.response?.data
      const msg = data?.error || data?.message || data?.msg
      let text =
        msg ||
        (ax.response?.status === 500
          ? 'Server error — restart the backend (cd backend && .venv/bin/python run.py --all) and try again.'
          : 'Failed to create project')
      if (ax.response?.status === 409 && /already exists/i.test(text)) {
        text += ' — open it from the folder list, or delete it first. If NAS folder is missing, use Sync NAS on WA Projects.'
      }
      setCreateError(text)
      toast.error(text)
    } finally {
      setCreating(false)
    }
  }

  function openEdit(project: WaProject) {
    setEditError(null)
    setEditTarget(project)
    setEditSyncNas(Boolean(nasStatus?.connected))
    setEditNasFolderName(project.nasFolderName || project.code)
  }

  async function handleEdit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!editTarget || savingEdit) return
    setEditError(null)
    setSavingEdit(true)
    const form = new FormData(e.currentTarget)
    const isBucket = isNasBucketFolderCode(editTarget.code)
    const folderName = editNasFolderName.trim()
    const useUnifiedName = isBucket || Boolean(nasStatus?.connected)
    const codeVal = useUnifiedName ? folderName : folderName || editTarget.code
    if (!folderName) {
      setEditError('Name is required')
      setSavingEdit(false)
      return
    }
    try {
      await updateProject(editTarget.id, {
        ...(!isBucket ? { code: codeVal } : {}),
        nasFolderName: folderName,
        location: (form.get('location') as string) || '',
        stage: form.get('stage') as string,
        status: form.get('status') as string,
        syncNas: editSyncNas,
      })
      await fetchProjects()
      setEditTarget(null)
      toast.success(
        editSyncNas && nasStatus?.connected
          ? 'Project updated — web and NAS folder synced'
          : 'Project updated'
      )
      if (nasStatus?.connected) {
        void syncNasFromDrive()
          .then(() => fetchProjects())
          .catch(() => {})
        fetchNasStatus()
      }
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { error?: string } } }
      const text = ax.response?.data?.error || 'Failed to update project'
      setEditError(text)
      toast.error(text)
    } finally {
      setSavingEdit(false)
    }
  }

  async function handleDelete() {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    try {
      const body = await deleteProject(deleteTarget.id, deleteNasFolder)
      const msg =
        body?.message ||
        (deleteNasFolder
          ? `Project ${deleteTarget.code} and NAS folder removed`
          : `Project ${deleteTarget.code} deleted`)
      toast.success(msg, { duration: body?.nasQuarantined ? 6000 : 4000 })
      setDeleteTarget(null)
      setDeleteNasFolder(false)
      await fetchProjects()
      fetchNasStatus()
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { error?: string } } }
      toast.error(ax.response?.data?.error || 'Failed to delete project')
    } finally {
      setDeleting(false)
    }
  }

  async function handleDeleteNasOnlyFolder() {
    if (!deleteNasOnlyFolder) return
    setDeleting(true)
    try {
      const data = await deleteNasRootFolder(deleteNasOnlyFolder) as {
        quarantined?: boolean
        alreadyRemoved?: boolean
        message?: string
      }
      if (data.message) {
        toast.success(data.message, { duration: 6000 })
      } else {
        toast.success(`NAS folder ${deleteNasOnlyFolder} deleted`)
      }
      setDeleteNasOnlyFolder(null)
      fetchNasStatus()
      fetchProjects()
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { error?: string } } }
      toast.error(ax.response?.data?.error || 'Failed to delete NAS folder')
    } finally {
      setDeleting(false)
    }
  }

  function bucketNasFolderName(bucket: WaProjectBucket): string {
    if (isStandaloneBucketCode(bucket.code)) return standaloneBucketDisplayCode(bucket.code)
    return bucket.code
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">Manage Projects</h1>
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
          <p className="text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
        </div>
        <button
          onClick={() => {
            setCreateError(null)
            setDialogOpen(true)
          }}
          className="btn btn-primary text-sm px-3 py-1.5 flex items-center gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />New Project
        </button>
      </div>

      <div className="card p-4">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by code, NAS folder, location, status..."
              className="input pl-9 w-full"
            />
          </div>
          <select
            value={stageFilter}
            onChange={(e) => setStageFilter(e.target.value)}
            className="input sm:w-40"
          >
            <option value="">All stages</option>
            <option value="planning">Planning</option>
            <option value="active">Active</option>
            <option value="completed">Completed</option>
            <option value="hold">On Hold</option>
          </select>
        </div>
      </div>

      {/* Create dialog */}
      {dialogOpen && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-md mx-4">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">
              {createParentFolder ? 'Create subfolder' : 'Create Project'}
            </h2>
            {createParentFolder && (
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
                Shared drive path:{' '}
                <span className="font-mono font-medium text-slate-800 dark:text-slate-200">
                  {selectedBucketCode ? bucketFolderLabel(selectedBucketCode) : createParentFolder}/
                  <span className="text-sign-600 dark:text-sign-400">your code</span>
                </span>
              </p>
            )}
            {createError && (
              <div
                className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200"
                role="alert"
              >
                {createError}
              </div>
            )}
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  {createParentFolder ? 'Subfolder / project code' : 'Code (e.g. P-001)'}
                </label>
                <input
                  name="code"
                  required
                  placeholder={createParentFolder ? '2036 or PJ-2036' : 'P-001'}
                  className="input w-full font-mono"
                />
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  {createParentFolder
                    ? 'Folder name on NAS matches this code (must be unique in the app).'
                    : 'Unique project code; NAS folder uses the same code.'}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Location</label>
                <input name="location" className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Stage</label>
                <select name="stage" className="input w-full">
                  <option value="planning">Planning</option>
                  <option value="active">Active</option>
                  <option value="completed">Completed</option>
                  <option value="hold">On Hold</option>
                </select>
              </div>
              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setDialogOpen(false)}
                  disabled={creating}
                  className="btn btn-secondary flex-1"
                >
                  Cancel
                </button>
                <button type="submit" disabled={creating} className="btn btn-primary flex-1 inline-flex items-center justify-center gap-2">
                  {creating && <Loader2 className="h-4 w-4 animate-spin" />}
                  {creating ? 'Creating…' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>,
        document.body
      )}

      {editTarget && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-md mx-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">Edit project</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4 font-mono">{editTarget.code}</p>
            {editError && (
              <div
                className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200"
                role="alert"
              >
                {editError}
              </div>
            )}
            <form onSubmit={handleEdit} className="space-y-4">
              {nasStatus?.connected || isNasBucketFolderCode(editTarget.code) ? (
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                    NAS folder name
                  </label>
                  <input
                    name="nasFolderName"
                    required
                    value={editNasFolderName}
                    onChange={(ev) => setEditNasFolderName(ev.target.value)}
                    className="input w-full font-mono"
                  />
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                    {isNasBucketFolderCode(editTarget.code)
                      ? 'Name on the shared drive; enable sync below to rename on NAS.'
                      : 'App project code and NAS folder use this name; enable sync below to rename on the share.'}
                  </p>
                </div>
              ) : (
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Code</label>
                  <input
                    name="code"
                    required
                    value={editNasFolderName}
                    onChange={(ev) => setEditNasFolderName(ev.target.value)}
                    className="input w-full font-mono"
                  />
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Location</label>
                <input
                  name="location"
                  defaultValue={editTarget.location || ''}
                  placeholder="Optional note (e.g. site address)"
                  className="input w-full"
                />
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  App-only field — NAS sync does not fill this; imported projects start empty.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Stage</label>
                <select name="stage" defaultValue={editTarget.stage} className="input w-full">
                  <option value="planning">Planning</option>
                  <option value="active">Active</option>
                  <option value="completed">Completed</option>
                  <option value="hold">On Hold</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Status</label>
                <select name="status" defaultValue={editTarget.status} className="input w-full">
                  <option value="active">Active</option>
                  <option value="archived">Archived</option>
                </select>
              </div>
              {nasStatus?.connected && (
                <label className="flex items-start gap-2 p-3 rounded-lg border border-slate-200 dark:border-slate-700 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <input
                    type="checkbox"
                    checked={editSyncNas}
                    onChange={(e) => setEditSyncNas(e.target.checked)}
                    className="mt-0.5 rounded border-slate-300 text-sign-600 focus:ring-sign-500"
                  />
                  <div>
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-200">Sync rename to NAS</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      Renames the folder on the shared drive to match the name above.
                    </p>
                  </div>
                </label>
              )}
              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEditTarget(null)}
                  disabled={savingEdit}
                  className="btn btn-secondary flex-1"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingEdit}
                  className="btn btn-primary flex-1 inline-flex items-center justify-center gap-2"
                >
                  {savingEdit && <Loader2 className="h-4 w-4 animate-spin" />}
                  {savingEdit ? 'Saving…' : 'Save'}
                </button>
              </div>
            </form>
          </div>
        </div>,
        document.body
      )}

      {deleteNasOnlyFolder && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-md mx-4">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">Delete NAS folder</h2>
            <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
              Remove folder{' '}
              <span className="font-mono font-semibold">{deleteNasOnlyFolder}</span> from the shared drive only.
              No app project will be removed (there is none linked).
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setDeleteNasOnlyFolder(null)}
                className="btn btn-secondary flex-1"
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteNasOnlyFolder}
                disabled={deleting}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg disabled:opacity-50"
              >
                {deleting ? 'Deleting…' : 'Delete on NAS'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Delete confirmation dialog */}
      {deleteTarget && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-md mx-4">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">Delete Project</h2>
            <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
              Are you sure you want to delete project <span className="font-mono font-semibold">{deleteTarget.code}</span>?
              This will also delete all associated records.
            </p>

            {nasStatus?.connected && (
              <label className="flex items-center gap-2 p-3 rounded-lg border border-slate-200 dark:border-slate-700 mb-4 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <input
                  type="checkbox"
                  checked={deleteNasFolder}
                  onChange={(e) => setDeleteNasFolder(e.target.checked)}
                  className="rounded border-slate-300 text-sign-600 focus:ring-sign-500"
                />
                <div>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                    Also delete NAS folder
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    One step: same as deleting the project, also removes the NAS folder (no second dialog)
                  </p>
                </div>
              </label>
            )}

            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setDeleteTarget(null); setDeleteNasFolder(false) }}
                className="btn btn-secondary flex-1"
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <FolderOpen className="h-10 w-10 text-slate-300 dark:text-slate-600 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">No projects yet</p>
        </div>
      ) : atBucketRoot && filteredBuckets.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Search className="h-10 w-10 text-slate-300 dark:text-slate-600 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">No folders match your filters</p>
        </div>
      ) : !atBucketRoot && filteredSiteProjects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Search className="h-10 w-10 text-slate-300 dark:text-slate-600 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {hasFilters ? 'No projects match your filters' : 'No site projects in this folder yet'}
          </p>
        </div>
      ) : atBucketRoot ? (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-800/50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Folder</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Site projects</th>
                <th className="px-4 py-2.5 w-24"></th>
                <th className="px-4 py-2.5 w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {filteredBuckets.map((bucket) => {
                const title = isRangeBucketCode(bucket.code)
                  ? bucket.code
                  : isStandaloneBucketCode(bucket.code)
                    ? standaloneBucketDisplayCode(bucket.code)
                    : bucket.code
                const adminProj = bucketAdminProject(bucket, projects)
                const nasFolderName = bucketNasFolderName(bucket)
                return (
                  <tr
                    key={bucket.code}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors cursor-pointer"
                    onClick={() => setSelectedBucketCode(bucket.code)}
                  >
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-2 font-mono font-semibold text-slate-800 dark:text-slate-200">
                        <Folder className="h-4 w-4 text-sign-600 dark:text-sign-400 shrink-0" />
                        {title}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">{bucketSiteProjects(bucket).length}</td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-sign-600 dark:text-sign-400">
                        Open <ChevronRight className="h-3.5 w-3.5" />
                      </span>
                    </td>
                    <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1 justify-end">
                        {adminProj ? (
                          <>
                            <button
                              type="button"
                              onClick={() => openEdit(adminProj)}
                              className="p-1 text-slate-400 hover:text-sign-600 dark:hover:text-sign-400 transition-colors"
                              title="Edit folder project"
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                              setDeleteNasFolder(false)
                              setDeleteTarget({ id: adminProj.id, code: adminProj.code })
                            }}
                              className="p-1 text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                              title="Delete project and records"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedBucketCode(bucket.code)
                                setCreateError(null)
                                setDialogOpen(true)
                              }}
                              className="p-1 text-slate-400 hover:text-sign-600 dark:hover:text-sign-400 transition-colors"
                              title="Add site project in this NAS folder"
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                            {nasStatus?.connected && (
                              <button
                                type="button"
                                onClick={() => setDeleteNasOnlyFolder(nasFolderName)}
                                className="p-1 text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                                title="Delete folder on NAS only (no app project)"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-800/50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Name</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Location</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Stage</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Status</th>
                <th className="px-4 py-2.5 w-12"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {filteredSiteProjects.map((project) => (
                <tr key={project.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                  <td className="px-4 py-2.5 font-mono font-semibold text-slate-800 dark:text-slate-200">
                    {project.nasFolderName || project.code}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">{project.location || '—'}</td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center rounded-md bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs font-medium text-slate-600 dark:text-slate-400">
                      {project.stage}
                    </span>
                  </td>
                  <td className="px-4 py-2.5"><WaStatusBadge status={project.status} size="sm" /></td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-1 justify-end">
                      <button
                        type="button"
                        onClick={() => openEdit(project)}
                        className="p-1 text-slate-400 hover:text-sign-600 dark:hover:text-sign-400 transition-colors"
                        title="Edit project"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setDeleteNasFolder(false)
                          setDeleteTarget({ id: project.id, code: project.code })
                        }}
                        className="p-1 text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                        title="Delete project"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
