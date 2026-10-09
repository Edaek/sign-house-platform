import { useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useWaStore, type PoolImage } from '../../store/waStore'
import toast from 'react-hot-toast'
import {
  Image,
  Check,
  RefreshCw,
  User,
  Clock,
  FolderOpen,
  ZoomIn,
  RotateCcw,
  Trash2,
  FileText,
  Film,
  File,
  ExternalLink,
} from 'lucide-react'
import {
  poolFileSrc,
  poolDisplayName,
  poolMediaKind,
  poolIsPreviewableImage,
  poolFileExtension,
} from '../../lib/waPoolMedia'
import { formatWaProjectLabel } from '../../lib/waProjects'

function formatPhone(phone: string, name?: string) {
  if (name) return `${name} (${phone})`
  return phone
}

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

export default function WaImagePoolPage() {
  const { poolImages, poolStats, projects, fetchPoolImages, fetchPoolStats, fetchProjects, assignImages, retryDownload, deletePoolImages } = useWaStore()
  const [statusFilter, setStatusFilter] = useState<'unassigned' | 'assigned' | 'all'>('unassigned')
  const [phoneFilter, setPhoneFilter] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [assignDialogOpen, setAssignDialogOpen] = useState(false)
  const [assignImageIds, setAssignImageIds] = useState<string[]>([])
  const [assigningProjectId, setAssigningProjectId] = useState('')
  const [assigning, setAssigning] = useState(false)
  const [retrying, setRetrying] = useState<Set<string>>(new Set())
  const [previewItem, setPreviewItem] = useState<PoolImage | null>(null)
  const [loading, setLoading] = useState(true)

  const loadData = useCallback(async () => {
    setLoading(true)
    const params: Record<string, string> = { status: statusFilter }
    if (phoneFilter) params.phone = phoneFilter
    await fetchPoolImages(params)
    setSelected(new Set())
    setLoading(false)
  }, [statusFilter, phoneFilter, fetchPoolImages])

  useEffect(() => {
    loadData()
    fetchPoolStats()
    fetchProjects()
  }, [loadData, fetchPoolStats, fetchProjects])

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAll() {
    if (selected.size === poolImages.length) setSelected(new Set())
    else setSelected(new Set(poolImages.map((img) => img.id)))
  }

  async function handleAssign() {
    if (!assigningProjectId || assignImageIds.length === 0) return
    setAssigning(true)
    try {
      const data = await assignImages(assignImageIds, assigningProjectId)
      toast.success(`${data.assigned} file${data.assigned === 1 ? '' : 's'} assigned to ${data.projectCode}`)
      setAssignDialogOpen(false)
      setAssignImageIds([])
      setAssigningProjectId('')
      loadData()
      fetchPoolStats()
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ||
        'Failed to assign files'
      toast.error(msg)
    } finally {
      setAssigning(false)
    }
  }

  async function handleRetryDownload(imageId: string) {
    setRetrying((prev) => new Set(prev).add(imageId))
    try {
      const data = await retryDownload([imageId])
      if (data.succeeded > 0) {
        toast.success('Image downloaded successfully')
        loadData()
        fetchPoolStats()
      } else {
        toast.error('Download failed — media may have expired')
      }
    } catch {
      toast.error('Retry request failed')
    } finally {
      setRetrying((prev) => { const next = new Set(prev); next.delete(imageId); return next })
    }
  }

  async function handleDeleteFailed(imageId: string) {
    try {
      const data = await deletePoolImages([imageId])
      toast.success(`Removed ${data.deleted} image record(s)`)
      loadData()
      fetchPoolStats()
    } catch {
      toast.error('Failed to delete')
    }
  }

  const grouped = poolImages.reduce<Record<string, PoolImage[]>>((acc, img) => {
    const key = img.phone
    if (!acc[key]) acc[key] = []
    acc[key].push(img)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white flex items-center gap-2.5">
            Media Pool
            {poolStats && poolStats.totalUnassigned > 0 && (
              <span className="inline-flex items-center justify-center rounded-full bg-sign-500 px-2.5 py-0.5 text-xs font-semibold text-white">
                {poolStats.totalUnassigned}
              </span>
            )}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Photos and documents from WhatsApp waiting to be assigned to projects
          </p>
        </div>
        <button onClick={() => { loadData(); fetchPoolStats() }} className="btn btn-secondary text-sm px-3 py-1.5 flex items-center gap-1.5">
          <RefreshCw className="h-3.5 w-3.5" />Refresh
        </button>
      </div>

      {/* Stats bar */}
      {poolStats && (
        <div className="flex gap-4">
          <div className="card px-4 py-3 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Unassigned</p>
            <p className="text-2xl font-bold text-sign-600 dark:text-sign-400 mt-1">{poolStats.totalUnassigned}</p>
          </div>
          <div className="card px-4 py-3 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Assigned</p>
            <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{poolStats.totalAssigned}</p>
          </div>
          <div className="card px-4 py-3 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Senders</p>
            <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{poolStats.bySender.length}</p>
          </div>
        </div>
      )}

      {/* Filters + actions */}
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as 'unassigned' | 'assigned' | 'all')}
          className="input px-3 py-2 text-sm w-auto"
        >
          <option value="unassigned">Unassigned</option>
          <option value="assigned">Assigned</option>
          <option value="all">All</option>
        </select>
        <select
          value={phoneFilter}
          onChange={(e) => setPhoneFilter(e.target.value)}
          className="input px-3 py-2 text-sm w-auto"
        >
          <option value="">All senders</option>
          {poolStats?.bySender.map((s) => (
            <option key={s.id} value={s.id}>{formatPhone(s.id, s.senderName)} ({s.count})</option>
          ))}
        </select>
        <div className="flex-1" />
        {poolImages.length > 0 && statusFilter !== 'assigned' && (
          <>
            <button onClick={selectAll} className="btn btn-secondary text-sm px-3 py-1.5">
              {selected.size === poolImages.length ? 'Deselect All' : 'Select All'}
            </button>
            {selected.size > 0 && (
              <button
                onClick={() => {
                  setAssignImageIds(Array.from(selected))
                  setAssignDialogOpen(true)
                }}
                className="btn btn-primary text-sm px-3 py-1.5 flex items-center gap-1.5"
              >
                <FolderOpen className="h-3.5 w-3.5" />Assign {selected.size} to Project
              </button>
            )}
          </>
        )}
      </div>

      {/* Image grid grouped by sender */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : poolImages.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Image className="h-10 w-10 text-slate-300 dark:text-slate-600 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {statusFilter === 'unassigned' ? 'No unassigned files. All caught up!' : 'No files found matching your filters.'}
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([phone, imgs]) => (
            <div key={phone} className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
              <div className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-4 py-2.5 flex items-center gap-2">
                <User className="h-4 w-4 text-slate-400" />
                <span className="text-sm font-medium text-slate-800 dark:text-slate-200">{formatPhone(phone, imgs[0].senderName)}</span>
                <span className="text-xs text-slate-500 dark:text-slate-400">{imgs.length} file{imgs.length === 1 ? '' : 's'}</span>
              </div>
              <div className="p-3 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                {imgs.map((img) => {
                  const isSelected = selected.has(img.id)
                  return (
                    <div
                      key={img.id}
                      className={`group relative rounded-lg border overflow-hidden cursor-pointer transition-all ${
                        isSelected ? 'ring-2 ring-sign-500 border-sign-500' : 'border-slate-200 dark:border-slate-700 hover:border-slate-400'
                      }`}
                      onClick={() => !img.projectId && toggleSelect(img.id)}
                    >
                      <div className="aspect-[4/3] relative bg-slate-100 dark:bg-slate-800">
                        {img.imagePath ? (
                          poolIsPreviewableImage(img) ? (
                            <>
                              <img src={poolFileSrc(img.imagePath)} alt={poolDisplayName(img)} className="w-full h-full object-cover" />
                              <button
                                type="button"
                                className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center"
                                onClick={(e) => { e.stopPropagation(); setPreviewItem(img) }}
                              >
                                <ZoomIn className="h-6 w-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                              </button>
                            </>
                          ) : (
                            <div className="w-full h-full flex flex-col items-center justify-center gap-2 p-3 text-center">
                              {poolMediaKind(img) === 'document' && <FileText className="h-10 w-10 text-sign-600 dark:text-sign-400" />}
                              {poolMediaKind(img) === 'video' && <Film className="h-10 w-10 text-sign-600 dark:text-sign-400" />}
                              {poolMediaKind(img) === 'file' && <File className="h-10 w-10 text-slate-500" />}
                              <span className="text-xs font-bold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                                {poolFileExtension(img)}
                              </span>
                              <p className="text-[10px] text-slate-500 dark:text-slate-400 line-clamp-2 w-full">{poolDisplayName(img)}</p>
                              <a
                                href={poolFileSrc(img.imagePath)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="btn btn-secondary text-[10px] px-2 py-1 inline-flex items-center gap-1"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <ExternalLink className="h-3 w-3" />Open
                              </a>
                            </div>
                          )
                        ) : (
                          <div className="w-full h-full flex flex-col items-center justify-center text-slate-400 gap-1.5">
                            <Image className="h-7 w-7 opacity-40" />
                            <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">Download failed</span>
                            <div className="flex gap-1.5">
                              <button
                                className="btn btn-primary text-[10px] px-2 py-1 disabled:opacity-50"
                                disabled={retrying.has(img.id)}
                                onClick={(e) => { e.stopPropagation(); handleRetryDownload(img.id) }}
                              >
                                <RotateCcw className={`h-3 w-3 ${retrying.has(img.id) ? 'animate-spin' : ''}`} />
                                {retrying.has(img.id) ? '...' : 'Retry'}
                              </button>
                              <button
                                className="btn btn-secondary text-[10px] px-2 py-1"
                                onClick={(e) => { e.stopPropagation(); handleDeleteFailed(img.id) }}
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </div>
                          </div>
                        )}
                        {!img.projectId && (
                          <div className={`absolute top-2 left-2 h-5 w-5 rounded border-2 flex items-center justify-center transition-colors ${
                            isSelected ? 'bg-sign-500 border-sign-500' : 'bg-white/80 border-slate-300 group-hover:border-slate-400'
                          }`}>
                            {isSelected && <Check className="h-3 w-3 text-white" />}
                          </div>
                        )}
                        {img.projectCode && (
                          <div className="absolute top-2 right-2 inline-flex items-center rounded bg-sign-500/90 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                            {img.projectCode}
                          </div>
                        )}
                      </div>
                      <div className="px-2.5 py-2 space-y-0.5">
                        <div className="flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400">
                          <Clock className="h-3 w-3" />{timeAgo(img.createdAt)}
                        </div>
                        {img.caption && <p className="text-xs text-slate-800 dark:text-slate-200 truncate">{img.caption}</p>}
                        {img.projectCode && (
                          <p className="text-[11px] text-sign-600 dark:text-sign-400 font-medium truncate">
                            {img.projectName && img.projectName.toLowerCase() !== img.projectCode.toLowerCase()
                              ? `${img.projectCode} - ${img.projectName}`
                              : img.projectCode}
                          </p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Assign dialog — portal to body so mask covers full viewport (no layout offset) */}
      {assignDialogOpen &&
        createPortal(
          <div
            className="fixed inset-0 z-[10040] flex items-center justify-center bg-black/50 p-4"
            role="presentation"
            onClick={() => {
              setAssignDialogOpen(false)
              setAssignImageIds([])
            }}
            onKeyDown={(e) => e.key === 'Escape' && setAssignDialogOpen(false)}
          >
            <div
              className="card p-6 w-full max-w-md max-h-[min(90vh,calc(100vh-2rem))] overflow-y-auto space-y-4 shadow-xl"
              role="dialog"
              aria-modal
              onClick={(e) => e.stopPropagation()}
            >
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                Assign {assignImageIds.length} file{assignImageIds.length === 1 ? '' : 's'} to project
              </h2>
              <select
                value={assigningProjectId}
                onChange={(e) => setAssigningProjectId(e.target.value)}
                className="input w-full"
              >
                <option value="">Select a project...</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {formatWaProjectLabel(p)}
                  </option>
                ))}
              </select>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setAssignDialogOpen(false)
                    setAssignImageIds([])
                  }}
                  className="btn btn-secondary"
                >
                  Cancel
                </button>
                <button type="button" onClick={handleAssign} disabled={!assigningProjectId || assigning} className="btn btn-primary">
                  {assigning ? 'Assigning...' : 'Assign'}
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {/* Preview */}
      {previewItem?.imagePath &&
        createPortal(
          <div
            className="fixed inset-0 z-[10040] bg-black/80 flex items-center justify-center p-4"
            onClick={() => setPreviewItem(null)}
            onKeyDown={(e) => e.key === 'Escape' && setPreviewItem(null)}
            role="presentation"
          >
            <div className="max-h-[90vh] max-w-[90vw] w-full flex flex-col items-center" onClick={(e) => e.stopPropagation()}>
              {poolMediaKind(previewItem) === 'document' && poolDisplayName(previewItem).toLowerCase().endsWith('.pdf') ? (
                <iframe
                  title={poolDisplayName(previewItem)}
                  src={poolFileSrc(previewItem.imagePath)}
                  className="w-full h-[85vh] rounded-lg bg-white"
                />
              ) : poolIsPreviewableImage(previewItem) ? (
                <img src={poolFileSrc(previewItem.imagePath)} alt={poolDisplayName(previewItem)} className="max-h-[90vh] max-w-[90vw] object-contain rounded-lg" />
              ) : (
                <div className="card p-6 text-center space-y-3">
                  <FileText className="h-12 w-12 mx-auto text-sign-500" />
                  <p className="text-sm text-slate-700 dark:text-slate-200">{poolDisplayName(previewItem)}</p>
                  <a href={poolFileSrc(previewItem.imagePath)} target="_blank" rel="noopener noreferrer" className="btn btn-primary text-sm">
                    Open / Download
                  </a>
                </div>
              )}
              <button type="button" className="mt-3 text-sm text-white/80 hover:text-white" onClick={() => setPreviewItem(null)}>
                Close
              </button>
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}
