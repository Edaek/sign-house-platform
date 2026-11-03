import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import {
  ChevronDown,
  ChevronRight,
  FileText,
  HardDrive,
  Loader2,
  MessageSquare,
  RefreshCw,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../../lib/api'
import type { WaRecord } from '../../store/waStore'
import WaStatusBadge from './StatusBadge'
import RecordDetailDrawer from './RecordDetailDrawer'
import { recordRemarkDisplay } from '../../lib/waRecordRemark'
import {
  buildSiteDayGroups,
  basenamePath,
  type NasFileEntry,
  waPhotoForNasFile,
  waRecordImagePhotos,
} from '../../lib/nasSiteDays'

function photoSrc(photo: string) {
  return photo.startsWith('/uploads/') ? `/api/wa/uploads${photo.replace('/uploads', '')}` : photo
}

function nasImagePreviewUrl(
  projectId: string,
  relativePath: string,
  nasFolderParams: Record<string, string>,
) {
  const q = new URLSearchParams({ path: relativePath })
  if (nasFolderParams.nasFolderName) q.set('nasFolderName', nasFolderParams.nasFolderName)
  if (nasFolderParams.nasParentBucket) q.set('nasParentBucket', nasFolderParams.nasParentBucket)
  return `/api/wa/projects/${projectId}/nas/media?${q.toString()}`
}

function NasTxtEditor({
  projectId,
  file,
  nasConnected,
  nasFolderParams,
}: {
  projectId: string
  file: NasFileEntry
  nasConnected: boolean
  nasFolderParams: Record<string, string>
}) {
  const path = file.relativePath || file.name
  const [content, setContent] = useState('')
  const [serverModified, setServerModified] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (!path || !nasConnected) return
    let cancelled = false
    setLoading(true)
    void api
      .get<{ ok: boolean; content?: string; modified?: string; error?: string }>(
        `/wa/projects/${projectId}/nas/txt/content`,
        { params: { path, ...nasFolderParams } },
      )
      .then(({ data }) => {
        if (cancelled || !data.ok) return
        setContent(data.content ?? '')
        setServerModified(data.modified || null)
        setDirty(false)
      })
      .catch(() => {
        if (!cancelled) toast.error('Failed to load remark file')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [path, projectId, nasConnected, nasFolderParams.nasFolderName, nasFolderParams.nasParentBucket])

  async function save() {
    if (!path || saving) return
    setSaving(true)
    try {
      const { data } = await api.put<{ ok: boolean; modified?: string; error?: string }>(
        `/wa/projects/${projectId}/nas/txt/content`,
        { path, content },
        { params: nasFolderParams },
      )
      if (!data.ok) {
        toast.error(data.error || 'Save failed')
        return
      }
      setServerModified(data.modified || null)
      setDirty(false)
      toast.success('Saved to NAS')
    } catch {
      toast.error('Save failed')
    } finally {
      setSaving(false)
    }
  }

  if (!nasConnected) {
    return <p className="text-xs text-slate-500">NAS offline — remark not loaded.</p>
  }

  return (
    <div className="space-y-2">
      <p className="text-[11px] font-mono text-slate-500 truncate" title={path}>
        {path}
      </p>
      {loading ? (
        <div className="flex justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-sign-500" />
        </div>
      ) : (
        <>
          <textarea
            value={content}
            onChange={(e) => {
              setContent(e.target.value)
              setDirty(true)
            }}
            rows={6}
            className="input w-full font-mono text-sm resize-y min-h-[120px]"
            spellCheck={false}
          />
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] text-slate-500">
              {dirty ? 'Unsaved' : serverModified ? `NAS ${serverModified.slice(0, 19).replace('T', ' ')} UTC` : ''}
            </p>
            <button
              type="button"
              disabled={!dirty || saving}
              onClick={() => void save()}
              className="btn btn-primary text-xs px-2.5 py-1 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save to NAS'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function DayNasImages({
  projectId,
  day,
  images,
  dayRecords,
  nasFolderParams,
}: {
  projectId: string
  day: string
  images: NasFileEntry[]
  dayRecords: WaRecord[]
  nasFolderParams: Record<string, string>
}) {
  if (images.length === 0) {
    return <p className="text-xs text-slate-500">No photos in Photo/{day}/ on the share.</p>
  }
  return (
    <ul className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
      {images.map((f) => {
        const rel = f.relativePath || f.name
        const waMatch = waPhotoForNasFile(rel, dayRecords)
        const src = waMatch ? photoSrc(waMatch) : nasImagePreviewUrl(projectId, rel, nasFolderParams)
        return (
          <li
            key={rel}
            className="rounded-md border border-slate-200 dark:border-slate-700 overflow-hidden bg-slate-50 dark:bg-slate-900/40"
          >
            <img
              src={src}
              alt=""
              loading="lazy"
              className="h-20 w-full object-cover bg-slate-100 dark:bg-slate-800"
              onError={(e) => {
                const el = e.currentTarget
                const nasUrl = nasImagePreviewUrl(projectId, rel, nasFolderParams)
                if (waMatch && !el.dataset.nasFallback) {
                  el.dataset.nasFallback = '1'
                  el.src = nasUrl
                  return
                }
                el.onerror = null
              }}
            />
            <p className="px-1.5 py-1 text-[10px] font-mono text-slate-600 dark:text-slate-400 truncate" title={rel}>
              {basenamePath(rel)}
            </p>
          </li>
        )
      })}
    </ul>
  )
}

function DayWaRecords({
  records,
  onSelect,
}: {
  records: WaRecord[]
  onSelect: (r: WaRecord) => void
}) {
  if (records.length === 0) {
    return <p className="text-xs text-slate-500">No WhatsApp submissions for this date.</p>
  }
  return (
    <ul className="space-y-2">
      {records.map((r) => (
        <li key={r.id}>
          <button
            type="button"
            onClick={() => onSelect(r)}
            className="w-full text-left rounded-md border border-slate-200 dark:border-slate-700 px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
          >
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="font-mono text-xs font-semibold text-sign-700 dark:text-sign-300">{r.referenceNumber}</span>
              <WaStatusBadge status={r.status} size="sm" />
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-400 line-clamp-2">{recordRemarkDisplay(r)}</p>
            {(() => {
              const imgs = waRecordImagePhotos(r)
              if (imgs.length === 0) return null
              return (
                <div className="flex gap-1 mt-2 flex-wrap">
                  {imgs.slice(0, 4).map((p) => (
                    <img key={p} src={photoSrc(p)} alt="" className="h-10 w-10 rounded object-cover border" />
                  ))}
                  {imgs.length > 4 && (
                    <span className="text-[10px] text-slate-500 self-center">+{imgs.length - 4}</span>
                  )}
                </div>
              )
            })()}
          </button>
        </li>
      ))}
    </ul>
  )
}

function SiteDaySection({
  group,
  projectId,
  nasConnected,
  nasFolderParams,
  defaultOpen,
}: {
  group: ReturnType<typeof buildSiteDayGroups>[number]
  projectId: string
  nasConnected: boolean
  nasFolderParams: Record<string, string>
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [selectedTxt, setSelectedTxt] = useState('')
  const [selectedRecord, setSelectedRecord] = useState<WaRecord | null>(null)

  useEffect(() => {
    if (!selectedTxt && group.txtFiles.length > 0) {
      setSelectedTxt(group.txtFiles[0].relativePath || group.txtFiles[0].name)
    }
  }, [group.txtFiles, selectedTxt])

  const summary = `${group.txtFiles.length} remark · ${group.nasImages.length} NAS photo · ${group.records.length} WA`

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center gap-2 px-4 py-3 bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-left"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
        <span className="font-semibold text-slate-900 dark:text-white tabular-nums">{group.day}</span>
        <span className="text-xs text-slate-500 ml-1">{summary}</span>
      </button>
      {open && (
        <div className="p-4 grid md:grid-cols-2 gap-6 border-t border-slate-200 dark:border-slate-700">
          <div className="space-y-4 min-w-0">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              <HardDrive className="h-3.5 w-3.5" />
              Shared drive
            </div>
            {group.txtFiles.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs text-slate-500">Site remark (.txt)</p>
                {group.txtFiles.length > 1 && (
                  <div className="flex flex-wrap gap-1.5">
                    {group.txtFiles.map((f) => {
                      const path = f.relativePath || f.name
                      const active = path === selectedTxt
                      return (
                        <button
                          key={path}
                          type="button"
                          onClick={() => setSelectedTxt(path)}
                          className={clsx(
                            'text-left px-2 py-0.5 rounded border text-[10px] font-mono max-w-full truncate',
                            active
                              ? 'border-sign-500 bg-sign-50 dark:bg-sign-950/40'
                              : 'border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/50',
                          )}
                          title={path}
                        >
                          <FileText className="h-3 w-3 inline mr-0.5 opacity-70" />
                          {basenamePath(path)}
                        </button>
                      )
                    })}
                  </div>
                )}
                {selectedTxt && (
                  <NasTxtEditor
                    projectId={projectId}
                    file={group.txtFiles.find((f) => (f.relativePath || f.name) === selectedTxt) || group.txtFiles[0]}
                    nasConnected={nasConnected}
                    nasFolderParams={nasFolderParams}
                  />
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-500">No .txt remark for this date on NAS.</p>
            )}
            <div>
              <p className="text-xs text-slate-500 mb-2">Photos under Photo/{group.day}/</p>
              <DayNasImages
                projectId={projectId}
                day={group.day}
                images={group.nasImages}
                dayRecords={group.records}
                nasFolderParams={nasFolderParams}
              />
            </div>
          </div>
          <div className="space-y-3 min-w-0 md:border-l md:border-slate-200 md:dark:border-slate-700 md:pl-6">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              <MessageSquare className="h-3.5 w-3.5" />
              WhatsApp records
            </div>
            <DayWaRecords records={group.records} onSelect={setSelectedRecord} />
          </div>
        </div>
      )}
      <RecordDetailDrawer record={selectedRecord} open={!!selectedRecord} onClose={() => setSelectedRecord(null)} />
    </div>
  )
}

export default function ProjectSiteDayTimeline({
  projectId,
  nasConnected,
  nasFolderParams,
  txtFiles,
  nasImages,
  records,
  loading,
  onRefresh,
}: {
  projectId: string
  nasConnected: boolean
  nasFolderParams: Record<string, string>
  txtFiles: NasFileEntry[]
  nasImages: NasFileEntry[]
  records: WaRecord[]
  loading?: boolean
  onRefresh?: () => void
}) {
  const groups = useMemo(
    () => buildSiteDayGroups(txtFiles, nasImages, records),
    [txtFiles, nasImages, records],
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Site log by date</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            NAS remarks &amp; photos aligned with WhatsApp submissions (Photo/YYYY-MM-DD).
          </p>
        </div>
        {onRefresh && (
          <button
            type="button"
            disabled={loading}
            onClick={onRefresh}
            className="text-xs text-sign-600 dark:text-sign-400 inline-flex items-center gap-1 hover:underline disabled:opacity-50"
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', loading && 'animate-spin')} />
            Refresh
          </button>
        )}
      </div>
      {loading && groups.length === 0 ? (
        <div className="flex justify-center py-12 rounded-lg border border-slate-200 dark:border-slate-700">
          <Loader2 className="h-7 w-7 animate-spin text-sign-500" />
        </div>
      ) : groups.length === 0 ? (
        <p className="text-sm text-slate-500 py-8 text-center rounded-lg border border-dashed border-slate-200 dark:border-slate-700">
          {nasConnected
            ? 'No dated site files or records yet. Remarks and photos appear under Photo/日期/ on the share.'
            : 'Connect NAS to load site files by date.'}
        </p>
      ) : (
        <div className="space-y-3">
          {groups.map((g, i) => (
            <SiteDaySection
              key={g.day}
              group={g}
              projectId={projectId}
              nasConnected={nasConnected}
              nasFolderParams={nasFolderParams}
              defaultOpen={i < 2}
            />
          ))}
        </div>
      )}
    </div>
  )
}
