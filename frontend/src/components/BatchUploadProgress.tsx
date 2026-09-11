import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  X, 
  FileText, 
  CheckCircle, 
  AlertCircle, 
  Loader2,
  Upload,
  Scan,
  Type,
  ImageIcon,
  Octagon,
  XCircle
} from 'lucide-react'
import clsx from 'clsx'
import { getProcessingStepColor } from '../lib/theme'

interface ProcessingFile {
  filename: string
  status: 'pending' | 'uploading' | 'converting' | 'detecting' | 'ocr' | 'completed' | 'error' | 'cancelled'
  progress: number
  error: string | null
  cancel_requested?: boolean
  floorplan_ids: string[]
  pages_total: number
  pages_processed: number
  shapes_detected: number
  started_at: string | null
  completed_at: string | null
}

interface BatchUploadJob {
  id: string
  job_id: string
  project_id: string
  status: 'pending' | 'processing' | 'completed' | 'error' | 'cancelled'
  cancel_requested?: boolean
  job_type?: string
  total_files: number
  processed_files: number
  files: ProcessingFile[]
  created_at: string
  updated_at: string
  completed_at: string | null
}

interface BatchUploadProgressProps {
  job: BatchUploadJob | null
  isOpen: boolean
  onClose: () => void
  onPoll: () => void
  onCancel?: (force?: boolean) => void | Promise<void>
  onCancelFile?: (fileIndex: number, force?: boolean) => void | Promise<void>
}

const isFileCancellable = (status: ProcessingFile['status']) =>
  !['completed', 'error', 'cancelled'].includes(status)

const getStatusIcon = (status: ProcessingFile['status']) => {
  const { icon } = getProcessingStepColor(status)
  const className = `w-4 h-4 ${icon}`
  switch (status) {
    case 'pending':
      return <FileText className={className} />
    case 'uploading':
      return <Upload className={className} />
    case 'converting':
      return <ImageIcon className={className} />
    case 'detecting':
      return <Scan className={className} />
    case 'ocr':
      return <Type className={className} />
    case 'completed':
      return <CheckCircle className={className} />
    case 'error':
      return <AlertCircle className={className} />
    case 'cancelled':
      return <Octagon className={className} />
  }
}

const getStatusText = (status: ProcessingFile['status']) => {
  switch (status) {
    case 'pending':
      return 'Waiting...'
    case 'uploading':
      return 'Uploading...'
    case 'converting':
      return 'Converting PDF...'
    case 'detecting':
      return 'Detecting shapes...'
    case 'ocr':
      return 'Running OCR...'
    case 'completed':
      return 'Completed'
    case 'error':
      return 'Failed'
    case 'cancelled':
      return 'Cancelled'
  }
}

export default function BatchUploadProgress({ job, isOpen, onClose, onPoll, onCancel, onCancelFile }: BatchUploadProgressProps) {
  const pollIntervalRef = useRef<number | null>(null)
  const [isCancelling, setIsCancelling] = useState(false)
  const [cancellingFiles, setCancellingFiles] = useState<Set<number>>(new Set())
  const [confirmCancel, setConfirmCancel] = useState<'job' | number | null>(null)
  
  useEffect(() => {
    if (isOpen && job && (job.status === 'pending' || job.status === 'processing')) {
      pollIntervalRef.current = window.setInterval(() => {
        onPoll()
      }, 2000)
    }
    
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [isOpen, job, onPoll])
  
  if (!isOpen || !job) return null
  
  const overallProgress = job.total_files > 0
    ? Math.round((job.files.reduce((sum, f) => sum + f.progress, 0) / job.total_files))
    : 0
  
  const completedCount = job.files.filter(f => f.status === 'completed').length
  const errorCount = job.files.filter(f => f.status === 'error').length
  const cancelledCount = job.files.filter(f => f.status === 'cancelled').length
  const isActive = job.status === 'pending' || job.status === 'processing'
  const isComplete = !isActive
  const isResume = job.job_type === 'batch_resume'
  
  const handleCancel = async (force = false) => {
    if (!onCancel || isCancelling) return
    setIsCancelling(true)
    try {
      await onCancel(force || job?.cancel_requested)
    } finally {
      setIsCancelling(false)
    }
  }

  const handleCancelFile = async (fileIndex: number) => {
    if (!onCancelFile || cancellingFiles.has(fileIndex)) return
    setCancellingFiles(prev => new Set(prev).add(fileIndex))
    try {
      await onCancelFile(fileIndex)
    } finally {
      setCancellingFiles(prev => {
        const next = new Set(prev)
        next.delete(fileIndex)
        return next
      })
    }
  }
  
  return (
    <AnimatePresence>
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-lg border border-slate-200 dark:border-slate-700 overflow-hidden"
        >
          <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
            <div className="flex items-center gap-3">
              {isComplete ? (
                job.status === 'cancelled' ? (
                  <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
                    <Octagon className="w-5 h-5 text-amber-500" />
                  </div>
                ) : errorCount > 0 ? (
                  <div className="w-10 h-10 rounded-full bg-red-500/20 flex items-center justify-center">
                    <AlertCircle className="w-5 h-5 text-red-400" />
                  </div>
                ) : (
                  <div className="w-10 h-10 rounded-full bg-sign-500/20 flex items-center justify-center">
                    <CheckCircle className="w-5 h-5 text-sign-500" />
                  </div>
                )
              ) : (
                <div className="w-10 h-10 rounded-full bg-sign-500/20 flex items-center justify-center">
                  <Loader2 className="w-5 h-5 text-sign-400 animate-spin" />
                </div>
              )}
              <div>
                <h3 className="font-semibold text-slate-900 dark:text-white">
                  {isComplete 
                    ? (job.status === 'cancelled'
                        ? 'Processing Cancelled'
                        : errorCount > 0 ? 'Upload Completed with Errors' : 'Upload Complete!')
                    : isResume
                      ? 'Resuming Floor Plans'
                      : 'Processing Floor Plans'
                  }
                </h3>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  {completedCount} of {job.total_files} files processed
                  {errorCount > 0 && ` (${errorCount} failed)`}
                  {cancelledCount > 0 && ` (${cancelledCount} cancelled)`}
                </p>
              </div>
            </div>
            
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              title={isComplete ? 'Close' : 'Minimize (processing continues in background)'}
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          
          <div className="p-4 border-b border-slate-200 dark:border-slate-700">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Overall Progress
              </span>
              <span className="text-sm font-mono text-slate-500 dark:text-slate-400">
                {overallProgress}%
              </span>
            </div>
            <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-sign-500 to-sign-400 rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${overallProgress}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
          </div>
          
          <div className="p-4 max-h-80 overflow-y-auto">
            <div className="space-y-3">
              {job.files.map((file, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className={clsx(
                    'group p-3 rounded-lg border transition-colors',
                    file.status === 'error'
                      ? 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800'
                      : file.status === 'cancelled'
                        ? 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800'
                      : file.status === 'completed'
                        ? 'bg-sign-500/5 dark:bg-sign-500/10 border-sign-200 dark:border-sign-800/40'
                        : 'bg-slate-50 dark:bg-slate-900/50 border-slate-200 dark:border-slate-700'
                  )}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      {getStatusIcon(file.status)}
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
                        {file.filename}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {isActive && onCancelFile && isFileCancellable(file.status) && (
                        <button
                          type="button"
                          onClick={() => setConfirmCancel(index)}
                          disabled={file.cancel_requested || cancellingFiles.has(index)}
                          className={clsx(
                            'text-xs px-2 py-0.5 rounded-md font-medium transition-opacity',
                            'border border-amber-300 text-amber-700 hover:bg-amber-50',
                            'dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950/30',
                            'disabled:opacity-50',
                            file.cancel_requested || cancellingFiles.has(index)
                              ? 'opacity-100'
                              : 'opacity-0 group-hover:opacity-100',
                          )}
                          title="Stop this file"
                        >
                          {file.cancel_requested || cancellingFiles.has(index) ? 'Stopping...' : 'Stop'}
                        </button>
                      )}
                      <span className={clsx(
                        'text-xs px-2 py-0.5 rounded-full font-medium',
                        file.status === 'error' && 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
                        file.status === 'cancelled' && 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300',
                        file.status === 'completed' && 'bg-sign-100 text-sign-700 dark:bg-sign-900/40 dark:text-sign-300',
                        !['completed', 'error', 'cancelled'].includes(file.status) && 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                      )}>
                        {getStatusText(file.status)}
                      </span>
                    </div>
                  </div>
                  
                  {file.status !== 'pending' && file.status !== 'error' && file.status !== 'cancelled' && (
                    <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                      <motion.div
                        className={clsx('h-full rounded-full', getProcessingStepColor(file.status).bar)}
                        initial={{ width: 0 }}
                        animate={{ width: `${file.progress}%` }}
                        transition={{ duration: 0.3 }}
                      />
                    </div>
                  )}
                  
                  {file.error && (
                    <p className="mt-2 text-xs text-red-500 dark:text-red-400">{file.error}</p>
                  )}
                  
                  {file.status === 'completed' && file.shapes_detected > 0 && (
                    <p className="mt-2 text-xs text-sign-600 dark:text-sign-400">
                      {file.shapes_detected} shapes detected across {file.pages_processed} pages
                    </p>
                  )}
                </motion.div>
              ))}
            </div>
          </div>
          
          <div className="p-4 border-t border-slate-200 dark:border-slate-700 flex gap-2 justify-end">
            {isActive && onCancel && (
              <button
                onClick={() => (job.cancel_requested ? handleCancel(true) : setConfirmCancel('job'))}
                disabled={isCancelling}
                className="btn border border-amber-300 text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950/30 disabled:opacity-50"
              >
                {isCancelling || job.cancel_requested ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
                    Force Stop
                  </>
                ) : (
                  'Stop Processing'
                )}
              </button>
            )}
            {isComplete && (
              <button
                onClick={onClose}
                className="flex-1 btn btn-primary"
              >
                Done
              </button>
            )}
          </div>
        </motion.div>
      </div>

      {confirmCancel !== null && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[60] p-4">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-sm border border-slate-200 dark:border-slate-700 p-6"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-950/40 flex items-center justify-center">
                <XCircle className="w-5 h-5 text-red-500" />
              </div>
              <h4 className="font-semibold text-slate-900 dark:text-white">
                {confirmCancel === 'job' ? 'Stop All Processing?' : 'Stop This File?'}
              </h4>
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400 mb-6">
              {confirmCancel === 'job'
                ? 'Are you sure you want to stop processing all files? Files already completed will be kept.'
                : 'Are you sure you want to stop processing this file?'}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmCancel(null)}
                className="flex-1 px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-600 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (confirmCancel === 'job') {
                    handleCancel()
                  } else {
                    handleCancelFile(confirmCancel as number)
                  }
                  setConfirmCancel(null)
                }}
                className="flex-1 px-4 py-2 rounded-lg bg-red-500 hover:bg-red-600 text-white text-sm font-medium transition-colors"
              >
                Confirm
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
