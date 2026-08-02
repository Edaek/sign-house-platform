import { useState } from 'react'
import WaStatusBadge from './StatusBadge'
import WaConfidenceBadge from './ConfidenceBadge'
import RecordDetailDrawer from './RecordDetailDrawer'
import { FileText, Image, Paperclip } from 'lucide-react'
import type { WaRecord, ConfidenceLevel } from '../../store/waStore'

function completionPercent(record: WaRecord): number {
  if (record.extractedFields.length === 0) return 0
  const filled = record.extractedFields.filter((f) => f.value && f.value !== '—').length
  return Math.round((filled / record.extractedFields.length) * 100)
}

function overallConfidence(record: WaRecord): ConfidenceLevel {
  if (record.extractedFields.length === 0) return 'gray'
  const levels: Record<string, number> = { green: 0, yellow: 0, red: 0, gray: 0 }
  for (const f of record.extractedFields) {
    levels[f.confidence] = (levels[f.confidence] || 0) + 1
  }
  if (levels.red > 0) return 'red'
  if (levels.yellow > 0) return 'yellow'
  if (levels.green > 0) return 'green'
  return 'gray'
}

function photoSrc(photo: string) {
  return photo.startsWith('/uploads/') ? `/api/wa/uploads${photo.replace('/uploads', '')}` : photo
}

function MediaCell({ record }: { record: WaRecord }) {
  if (record.photos.length > 0) {
    const firstPhoto = record.photos[0]
    const isImage = /\.(jpg|jpeg|png|webp|gif)$/i.test(firstPhoto)
    if (isImage) {
      return (
        <div className="flex items-center gap-1.5">
          <img src={photoSrc(firstPhoto)} alt="" className="h-7 w-7 rounded object-cover border" />
          {record.photos.length > 1 && (
            <span className="text-[10px] text-slate-500">+{record.photos.length - 1}</span>
          )}
        </div>
      )
    }
    return (
      <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
        <Image className="h-3.5 w-3.5" />
        <span>{record.photos.length}</span>
      </span>
    )
  }
  if (record.hasMedia) {
    return (
      <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
        <Paperclip className="h-3.5 w-3.5" />
        <span className="text-xs">pending</span>
      </span>
    )
  }
  return <span className="text-slate-400 dark:text-slate-600">—</span>
}

interface RecordTableProps {
  records: WaRecord[]
}

export default function WaRecordTable({ records }: RecordTableProps) {
  const [selectedRecord, setSelectedRecord] = useState<WaRecord | null>(null)

  return (
    <>
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-slate-50 dark:bg-slate-800/50">
              <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Ref</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Type</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Status</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Sender</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Message</th>
              <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Media</th>
              <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Fields</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
            {records.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center">
                  <FileText className="h-8 w-8 text-slate-400 dark:text-slate-600 mx-auto mb-2" />
                  <p className="text-sm text-slate-500 dark:text-slate-400">No records yet</p>
                </td>
              </tr>
            ) : (
              records.map((record) => {
                const pct = completionPercent(record)
                const conf = overallConfidence(record)
                return (
                  <tr
                    key={record.id}
                    className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                    onClick={() => setSelectedRecord(record)}
                  >
                    <td className="px-4 py-2.5 font-mono font-semibold text-xs">{record.referenceNumber}</td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center rounded-md bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs font-medium text-slate-700 dark:text-slate-300">
                        {record.type}
                      </span>
                    </td>
                    <td className="px-4 py-2.5"><WaStatusBadge status={record.status} size="sm" /></td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-400">{record.senderName || record.senderPhone}</td>
                    <td className="px-4 py-2.5 max-w-[180px] truncate text-slate-600 dark:text-slate-400">{record.rawMessage}</td>
                    <td className="px-4 py-2.5 text-center"><MediaCell record={record} /></td>
                    <td className="px-4 py-2.5 text-center">
                      {record.extractedFields.length > 0 ? (
                        <div className="flex items-center justify-center gap-1.5">
                          <div className="h-1.5 w-12 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                pct === 100 ? 'bg-emerald-500' : pct > 50 ? 'bg-blue-500' : 'bg-amber-500'
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <WaConfidenceBadge confidence={conf} />
                        </div>
                      ) : (
                        <span className="text-slate-400 dark:text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {new Date(record.createdAt).toLocaleDateString()}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <RecordDetailDrawer
        record={selectedRecord}
        open={!!selectedRecord}
        onClose={() => setSelectedRecord(null)}
      />
    </>
  )
}
