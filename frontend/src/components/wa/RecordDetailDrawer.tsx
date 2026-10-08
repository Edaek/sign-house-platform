import { useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import WaStatusBadge from './StatusBadge'
import WaConfidenceBadge from './ConfidenceBadge'
import { useWaStore, type WaRecord, type ConfidenceLevel } from '../../store/waStore'
import { recordRemarkDisplay } from '../../lib/waRecordRemark'
import toast from 'react-hot-toast'
import {
  CheckCircle2,
  XCircle,
  MessageSquare,
  Clock,
  User,
  Phone,
  Pencil,
  ImageIcon,
  Paperclip,
  ZoomIn,
  X,
} from 'lucide-react'

interface RecordDetailDrawerProps {
  record: WaRecord | null
  open: boolean
  onClose: () => void
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
      {children}
    </h3>
  )
}

function photoSrc(photo: string) {
  return photo.startsWith('/uploads/') ? `/api/wa/uploads${photo.replace('/uploads', '')}` : photo
}

export default function RecordDetailDrawer({ record, open, onClose }: RecordDetailDrawerProps) {
  const { confirmRecord, voidRecord, requestInfo, updateRecordField } = useWaStore()
  const [voidReason, setVoidReason] = useState('')
  const [showVoidDialog, setShowVoidDialog] = useState(false)
  const [requestInfoText, setRequestInfoText] = useState('')
  const [showRequestInfo, setShowRequestInfo] = useState(false)
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [previewImage, setPreviewImage] = useState<string | null>(null)

  if (!record) return null

  const isEditable = record.status !== 'completed' && record.status !== 'voided'

  async function handleConfirm() {
    setLoading(true)
    try {
      await confirmRecord(record!.id)
      toast.success('Record confirmed')
      onClose()
    } catch {
      toast.error('Failed to confirm record')
    } finally {
      setLoading(false)
    }
  }

  async function handleVoid() {
    if (voidReason.length < 5) {
      toast.error('Reason must be at least 5 characters')
      return
    }
    setLoading(true)
    try {
      await voidRecord(record!.id, voidReason)
      toast.success('Record voided')
      setShowVoidDialog(false)
      onClose()
    } catch {
      toast.error('Failed to void record')
    } finally {
      setLoading(false)
    }
  }

  async function handleRequestInfo() {
    if (!requestInfoText.trim()) return
    setLoading(true)
    try {
      await requestInfo(record!.id, requestInfoText)
      toast.success('Follow-up sent to worker')
      setShowRequestInfo(false)
      setRequestInfoText('')
      onClose()
    } catch {
      toast.error('Failed to send request')
    } finally {
      setLoading(false)
    }
  }

  async function handleFieldEdit(fieldName: string) {
    setLoading(true)
    try {
      await updateRecordField(record!.id, fieldName, editValue)
      toast.success('Field updated')
      setEditingField(null)
    } catch {
      toast.error('Failed to update field')
    } finally {
      setLoading(false)
    }
  }

  const drawerLayer =
    typeof document !== 'undefined' ? (
      <AnimatePresence>
        {open && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-[10040] bg-black/50"
              onClick={onClose}
              aria-hidden
            />
            <motion.div
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 300 }}
              className="fixed inset-y-0 right-0 z-[10041] w-[500px] sm:w-[600px] bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 overflow-y-auto shadow-2xl"
              role="dialog"
              aria-modal
            >
              {/* Header */}
              <div className="sticky top-0 z-10 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 px-6 py-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <h2 className="font-mono text-base font-semibold text-slate-900 dark:text-white">{record.referenceNumber}</h2>
                    <WaStatusBadge status={record.status} />
                  </div>
                  <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
                    <X className="h-4 w-4 text-slate-500" />
                  </button>
                </div>
                <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400 mt-1">
                  <span className="flex items-center gap-1"><User className="h-3 w-3" />{record.senderName || record.senderPhone}</span>
                  <span className="flex items-center gap-1"><Phone className="h-3 w-3" />{record.senderPhone}</span>
                  <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{new Date(record.createdAt).toLocaleString()}</span>
                </div>
              </div>

              <div className="px-6 py-5 space-y-6">
                {/* Actions */}
                {record.status === 'awaiting_review' && (
                  <div className="flex gap-2">
                    <button onClick={handleConfirm} disabled={loading} className="btn btn-primary text-sm px-3 py-1.5 flex items-center gap-1.5">
                      <CheckCircle2 className="h-3.5 w-3.5" />Confirm
                    </button>
                    <button onClick={() => setShowRequestInfo(true)} className="btn btn-secondary text-sm px-3 py-1.5 flex items-center gap-1.5">
                      <MessageSquare className="h-3.5 w-3.5" />Request Info
                    </button>
                    <button onClick={() => setShowVoidDialog(true)} className="btn btn-secondary text-sm px-3 py-1.5 flex items-center gap-1.5">
                      <XCircle className="h-3.5 w-3.5" />Void
                    </button>
                  </div>
                )}

                {showVoidDialog && (
                  <div className="card p-4 space-y-3">
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-200">Reason for voiding:</p>
                    <textarea value={voidReason} onChange={(e) => setVoidReason(e.target.value)} placeholder="Min 5 characters..." className="input w-full min-h-[60px]" />
                    <div className="flex gap-2">
                      <button onClick={handleVoid} disabled={loading} className="btn btn-primary text-sm px-3 py-1.5">Confirm Void</button>
                      <button onClick={() => setShowVoidDialog(false)} className="btn btn-secondary text-sm px-3 py-1.5">Cancel</button>
                    </div>
                  </div>
                )}

                {showRequestInfo && (
                  <div className="card p-4 space-y-3">
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-200">What info do you need?</p>
                    <textarea value={requestInfoText} onChange={(e) => setRequestInfoText(e.target.value)} placeholder="Describe what information is needed..." className="input w-full min-h-[60px]" />
                    <div className="flex gap-2">
                      <button onClick={handleRequestInfo} disabled={loading} className="btn btn-primary text-sm px-3 py-1.5">Send via WhatsApp</button>
                      <button onClick={() => setShowRequestInfo(false)} className="btn btn-secondary text-sm px-3 py-1.5">Cancel</button>
                    </div>
                  </div>
                )}

                {/* Classify remark from WhatsApp (编号后的备注) */}
                <section>
                  <SectionHeader>Remark</SectionHeader>
                  <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/30 p-3">
                    <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-300 whitespace-pre-wrap break-words">
                      {recordRemarkDisplay(record)}
                    </p>
                  </div>
                </section>

                {/* Media */}
                {(record.photos.length > 0 || record.hasMedia) && (
                  <section>
                    <SectionHeader>Media ({record.photos.length} file{record.photos.length !== 1 ? 's' : ''})</SectionHeader>
                    {record.photos.length > 0 ? (
                      <div className="grid grid-cols-2 gap-2">
                        {record.photos.map((photo, i) => {
                          const src = photoSrc(photo)
                          const isImage = /\.(jpg|jpeg|png|webp|gif)$/i.test(photo)
                          return isImage ? (
                            <button
                              key={i}
                              onClick={() => setPreviewImage(src)}
                              className="group relative block rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden bg-slate-100 dark:bg-slate-800"
                            >
                              <img src={src} alt={`Media ${i + 1}`} className="w-full aspect-[4/3] object-cover" />
                              <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
                                <ZoomIn className="h-5 w-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                              </div>
                            </button>
                          ) : (
                            <a
                              key={i}
                              href={src}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 p-3 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                            >
                              <ImageIcon className="h-5 w-5 text-slate-400" />
                              <span className="text-sm truncate">{photo.split('/').pop()}</span>
                            </a>
                          )
                        })}
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/30 px-3 py-2.5">
                        <Paperclip className="h-4 w-4 text-slate-400" />
                        <span className="text-sm text-slate-600 dark:text-slate-400">{record.mediaType || 'Media'} attached — download pending</span>
                      </div>
                    )}
                  </section>
                )}

                {/* Extracted Fields */}
                <section>
                  <SectionHeader>Extracted Fields</SectionHeader>
                  {record.extractedFields.length === 0 ? (
                    <p className="text-sm text-slate-500 dark:text-slate-400">No fields extracted yet</p>
                  ) : (
                    <div className="rounded-lg border border-slate-200 dark:border-slate-700 divide-y divide-slate-200 dark:divide-slate-700 overflow-hidden">
                      {record.extractedFields.map((field) => (
                        <div key={field.name} className="group flex items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                          <span className="font-medium text-slate-500 dark:text-slate-400 min-w-[110px] text-xs uppercase tracking-wide">{field.name}</span>
                          {editingField === field.name ? (
                            <div className="flex gap-1 flex-1">
                              <input value={editValue} onChange={(e) => setEditValue(e.target.value)} className="input h-7 text-sm flex-1" autoFocus />
                              <button onClick={() => handleFieldEdit(field.name)} className="btn btn-primary h-7 px-2 text-xs">Save</button>
                              <button onClick={() => setEditingField(null)} className="btn btn-secondary h-7 px-2 text-xs">Cancel</button>
                            </div>
                          ) : (
                            <>
                              <span className="flex-1 font-medium text-slate-800 dark:text-slate-200">{field.value || '—'}</span>
                              <WaConfidenceBadge confidence={field.confidence as ConfidenceLevel} />
                              {isEditable && (
                                <button
                                  className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 transition-opacity"
                                  onClick={() => { setEditingField(field.name); setEditValue(field.value) }}
                                >
                                  <Pencil className="h-3 w-3 text-slate-400" />
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                {/* Follow-up Thread */}
                {record.followUpThread.length > 0 && (
                  <section>
                    <SectionHeader>Follow-up Thread</SectionHeader>
                    <div className="space-y-2">
                      {record.followUpThread.map((entry, i) => (
                        <div key={i} className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Round {entry.round}</span>
                            <span className="text-[10px] text-slate-500 dark:text-slate-400">{new Date(entry.timestamp).toLocaleString()}</span>
                          </div>
                          <p className="text-sm"><span className="font-medium text-sign-600 dark:text-sign-400">Q:</span> {entry.question}</p>
                          {entry.answer && <p className="text-sm"><span className="font-medium text-slate-600 dark:text-slate-400">A:</span> {entry.answer}</p>}
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Status History */}
                {record.statusHistory.length > 0 && (
                  <section>
                    <SectionHeader>Status History</SectionHeader>
                    <div className="space-y-1">
                      {record.statusHistory.map((entry, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs py-1">
                          <time className="text-slate-500 dark:text-slate-400 w-[140px] shrink-0">{new Date(entry.timestamp).toLocaleString()}</time>
                          <div className="flex items-center gap-1">
                            <WaStatusBadge status={entry.from} size="sm" />
                            <span className="text-slate-400">→</span>
                            <WaStatusBadge status={entry.to} size="sm" />
                          </div>
                          {entry.reason && <span className="text-slate-500 dark:text-slate-400 truncate">({entry.reason})</span>}
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    ) : null

  return (
    <>
      {drawerLayer && createPortal(drawerLayer, document.body)}

      {previewImage &&
        createPortal(
          <div
            className="fixed inset-0 z-[10050] bg-black/80 flex items-center justify-center cursor-pointer"
            onClick={() => setPreviewImage(null)}
          >
            <img src={previewImage} alt="Preview" className="max-h-[90vh] max-w-[90vw] object-contain rounded-lg" />
          </div>,
          document.body,
        )}
    </>
  )
}
