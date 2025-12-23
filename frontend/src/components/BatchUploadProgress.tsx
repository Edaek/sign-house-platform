import { useEffect, useRef } from 'react'
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
  ImageIcon
} from 'lucide-react'
import clsx from 'clsx'

interface ProcessingFile {
  filename: string
  status: 'pending' | 'uploading' | 'converting' | 'detecting' | 'ocr' | 'completed' | 'error'
  progress: number
  error: string | null
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
  status: 'pending' | 'processing' | 'completed' | 'error'
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
}

const getStatusIcon = (status: ProcessingFile['status']) => {
  switch (status) {
    case 'pending':
      return <FileText className="w-4 h-4 text-slate-400" />
    case 'uploading':
      return <Upload className="w-4 h-4 text-blue-400 animate-pulse" />
    case 'converting':
      return <ImageIcon className="w-4 h-4 text-purple-400 animate-pulse" />
    case 'detecting':
      return <Scan className="w-4 h-4 text-amber-400 animate-pulse" />
    case 'ocr':
      return <Type className="w-4 h-4 text-cyan-400 animate-pulse" />
    case 'completed':
      return <CheckCircle className="w-4 h-4 text-emerald-400" />
    case 'error':
      return <AlertCircle className="w-4 h-4 text-red-400" />
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
  }
}

const getStatusColor = (status: ProcessingFile['status']) => {
  switch (status) {
    case 'pending':
      return 'bg-slate-500'
    case 'uploading':
      return 'bg-blue-500'
    case 'converting':
      return 'bg-purple-500'
    case 'detecting':
      return 'bg-amber-500'
    case 'ocr':
      return 'bg-cyan-500'
    case 'completed':
      return 'bg-emerald-500'
    case 'error':
      return 'bg-red-500'
  }
}

export default function BatchUploadProgress({ job, isOpen, onClose, onPoll }: BatchUploadProgressProps) {
  const pollIntervalRef = useRef<number | null>(null)
  
  // Poll for status updates
  useEffect(() => {
    if (isOpen && job && (job.status === 'pending' || job.status === 'processing')) {
      pollIntervalRef.current = window.setInterval(() => {
        onPoll()
      }, 2000)
    }
    
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
  }, [isOpen, job?.status, onPoll])
  
  if (!isOpen || !job) return null
  
  const overallProgress = job.total_files > 0 
    ? Math.round((job.files.reduce((sum, f) => sum + f.progress, 0) / job.total_files))
    : 0
  
  const completedCount = job.files.filter(f => f.status === 'completed').length
  const errorCount = job.files.filter(f => f.status === 'error').length
  const isComplete = job.status === 'completed' || job.status === 'error'
  
  return (
    <AnimatePresence>
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-lg border border-slate-200 dark:border-slate-700 overflow-hidden"
        >
          {/* Header */}
          <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
            <div className="flex items-center gap-3">
              {isComplete ? (
                errorCount > 0 ? (
                  <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
                    <AlertCircle className="w-5 h-5 text-amber-400" />
                  </div>
                ) : (
                  <div className="w-10 h-10 rounded-full bg-emerald-500/20 flex items-center justify-center">
                    <CheckCircle className="w-5 h-5 text-emerald-400" />
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
                    ? (errorCount > 0 ? 'Upload Completed with Errors' : 'Upload Complete!')
                    : 'Processing Floor Plans'
                  }
                </h3>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  {completedCount} of {job.total_files} files processed
                  {errorCount > 0 && ` (${errorCount} failed)`}
                </p>
              </div>
            </div>
            
            {isComplete && (
              <button
                onClick={onClose}
                className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>
          
          {/* Overall Progress */}
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
          
          {/* File List */}
          <div className="p-4 max-h-80 overflow-y-auto">
            <div className="space-y-3">
              {job.files.map((file, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className={clsx(
                    'p-3 rounded-lg border transition-colors',
                    file.status === 'error'
                      ? 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800'
                      : file.status === 'completed'
                        ? 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800'
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
                    <span className={clsx(
                      'text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap',
                      file.status === 'completed' && 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300',
                      file.status === 'error' && 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
                      file.status !== 'completed' && file.status !== 'error' && 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                    )}>
                      {getStatusText(file.status)}
                    </span>
                  </div>
                  
                  {/* Progress bar */}
                  <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className={clsx(
                        'h-full rounded-full transition-all duration-300',
                        getStatusColor(file.status)
                      )}
                      style={{ width: `${file.progress}%` }}
                    />
                  </div>
                  
                  {/* Details */}
                  {(file.pages_total > 0 || file.shapes_detected > 0) && (
                    <div className="mt-2 flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                      {file.pages_total > 0 && (
                        <span>
                          {file.pages_processed}/{file.pages_total} pages
                        </span>
                      )}
                      {file.shapes_detected > 0 && (
                        <span>
                          {file.shapes_detected} shapes detected
                        </span>
                      )}
                    </div>
                  )}
                  
                  {/* Error message */}
                  {file.error && (
                    <p className="mt-2 text-xs text-red-600 dark:text-red-400">
                      {file.error}
                    </p>
                  )}
                </motion.div>
              ))}
            </div>
          </div>
          
          {/* Footer */}
          {isComplete && (
            <div className="p-4 border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
              <button
                onClick={onClose}
                className="w-full btn btn-primary"
              >
                {errorCount > 0 ? 'Close & Review' : 'Done'}
              </button>
            </div>
          )}
        </motion.div>
      </div>
    </AnimatePresence>
  )
}

