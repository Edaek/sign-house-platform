import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import PageContainer from '../components/PageContainer'
import { motion } from 'framer-motion'
import { 
  Upload, 
  Layers,
  FolderOpen,
  ArrowRight,
  CheckCircle,
  Clock,
  AlertCircle,
  Download,
  ChevronLeft,
  Users,
  Play,
  FileText,
  X,
  Pencil,
  Check,
  Loader2,
  Eye,
  EyeOff
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import ProjectMembersModal from '../components/ProjectMembersModal'
import BatchUploadProgress from '../components/BatchUploadProgress'
import MarkerColorMenu from '../components/MarkerColorMenu'
import api from '../lib/api'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { DEFAULT_MARKER_COLORS, type MarkerColor } from '../lib/markerColors'

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { 
    currentProject, 
    fetchProject, 
    updateProject,
    uploadFloorplans,
    pollBatchStatus,
    cancelBatchJob,
    cancelBatchFile,
    resumeBatchProcessing,
    fetchActiveBatchJob,
    currentBatchJob,
    isBatchUploading,
    clearBatchJob,
    cancelBatchJob,
    cancelBatchFile,
    isLoading,
    watcherStatus,
    startWatcher,
    stopWatcher,
    fetchWatcherStatus,
    browseFolders,
  } = useProjectStore()
  const [showMembersModal, setShowMembersModal] = useState(false)
  const [showBatchProgress, setShowBatchProgress] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [isEditingName, setIsEditingName] = useState(false)
  const [editedName, setEditedName] = useState('')
  
  const [isReExtractingTitles, setIsReExtractingTitles] = useState(false)
  const [detectionMode, setDetectionMode] = useState<'fast' | 'accurate'>('accurate')
  const [markerColors, setMarkerColors] = useState<MarkerColor[]>(DEFAULT_MARKER_COLORS)

  // Import tab & folder watcher state
  const [importTab, setImportTab] = useState<'manual' | 'watcher'>('manual')
  const [watcherFolder, setWatcherFolder] = useState('')
  const [watcherMode, setWatcherMode] = useState<'fast' | 'accurate'>('accurate')
  const [folderBrowser, setFolderBrowser] = useState<{ current_path: string; parent_path: string | null; folders: { name: string; path: string }[] } | null>(null)

  const floorplanInputRef = useRef<HTMLInputElement>(null)
  const dropZoneRef = useRef<HTMLDivElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  
  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
      fetchActiveBatchJob(projectId)
      fetchWatcherStatus(projectId)
    }
  }, [projectId, fetchProject, fetchActiveBatchJob, fetchWatcherStatus])

  // Restore watcher folder from saved status
  useEffect(() => {
    if (watcherStatus?.watch_folder && !watcherFolder) {
      setWatcherFolder(watcherStatus.watch_folder)
    }
    if (watcherStatus?.detection_mode) {
      setWatcherMode(watcherStatus.detection_mode as 'fast' | 'accurate')
    }
  }, [watcherStatus])

  // Poll watcher status while running
  useEffect(() => {
    if (!projectId || watcherStatus?.status !== 'running') return
    const interval = setInterval(() => {
      fetchWatcherStatus(projectId)
      fetchProject(projectId)
    }, 5000)
    return () => clearInterval(interval)
  }, [projectId, watcherStatus?.status, fetchWatcherStatus, fetchProject])

  // Auto-load folder browser when switching to watcher tab
  useEffect(() => {
    if (importTab === 'watcher' && !folderBrowser && watcherStatus?.status !== 'running') {
      const startPath = watcherFolder || '~'
      browseFolders(startPath).then(data => setFolderBrowser(data)).catch(() => {
        browseFolders('~').then(data => setFolderBrowser(data)).catch(() => {})
      })
    }
  }, [importTab])
  
  // Handle file selection from input
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length > 0) {
      setSelectedFiles(prev => [...prev, ...files])
    }
    e.target.value = ''
  }

  
  // Handle drag and drop
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])
  
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    // Only set isDragging to false if we're leaving the drop zone entirely
    if (dropZoneRef.current && !dropZoneRef.current.contains(e.relatedTarget as Node)) {
      setIsDragging(false)
    }
  }, [])
  
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])
  
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    
    const files = Array.from(e.dataTransfer.files).filter(
      file => file.type === 'application/pdf'
    )
    
    if (files.length > 0) {
      setSelectedFiles(prev => [...prev, ...files])
    } else {
      toast.error('Please drop PDF files only')
    }
  }, [])
  
  // Remove a file from selection
  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index))
  }
  
  // Start batch upload
  const handleBatchUpload = async () => {
    if (!projectId || selectedFiles.length === 0) return

    const totalMB = selectedFiles.reduce((s, f) => s + f.size, 0) / 1024 / 1024
    const limitMB = 500
    if (totalMB > limitMB) {
      toast.error(`Total size ${totalMB.toFixed(0)}MB exceeds ${limitMB}MB limit. Please select fewer files.`)
      return
    }
    
    try {
      const job = await uploadFloorplans(projectId, selectedFiles, detectionMode, markerColors)
      setSelectedFiles([])
      setShowBatchProgress(true)
      toast.success(`Started processing ${job.total_files} PDF files`)
    } catch {
      toast.error('Failed to start upload')
    }
  }
  
  // Poll for batch status
  const handlePollStatus = useCallback(async () => {
    if (!projectId || !currentBatchJob) return
    
    try {
      await pollBatchStatus(projectId, currentBatchJob.job_id)
    } catch {
      // Silently handle poll errors
    }
  }, [projectId, currentBatchJob, pollBatchStatus])

  const handleCancelBatch = useCallback(async () => {
    if (!projectId || !currentBatchJob) return
    try {
      await cancelBatchJob(projectId, currentBatchJob.job_id)
      toast.success('Stop requested')
    } catch {
      toast.error('Failed to stop')
    }
  }, [projectId, currentBatchJob, cancelBatchJob])

  const handleCancelBatchFile = useCallback(async (fileIndex: number) => {
    if (!projectId || !currentBatchJob) return
    try {
      await cancelBatchFile(projectId, currentBatchJob.job_id, fileIndex)
      toast.success('Stop requested for file')
    } catch {
      toast.error('Failed to stop file')
    }
  }, [projectId, currentBatchJob, cancelBatchFile])

  const pendingFloorplanCount = currentProject?.floorplans?.filter(
    fp => fp.status === 'pending'
  ).length ?? 0

  const handleResumeProcessing = async () => {
    if (!projectId || pendingFloorplanCount === 0 || isBatchUploading) return
    try {
      const job = await resumeBatchProcessing(projectId, detectionMode, markerColors)
      setShowBatchProgress(true)
      toast.success(`Resumed processing for ${job.total_files} file(s)`)
    } catch {
      toast.error('Failed to resume processing')
    }
  }
  
  // Continue polling even when dialog is closed but job is still running
  useEffect(() => {
    if (!showBatchProgress && currentBatchJob && 
        (currentBatchJob.status === 'pending' || currentBatchJob.status === 'processing')) {
      const pollInterval = setInterval(() => {
        handlePollStatus()
      }, 2000)
      
      return () => clearInterval(pollInterval)
    }
  }, [showBatchProgress, currentBatchJob?.status, handlePollStatus])

  // Notify when batch job completes (regardless of whether progress modal is open)
  const prevBatchStatusRef = useRef<string | null>(null)
  useEffect(() => {
    const prev = prevBatchStatusRef.current
    const curr = currentBatchJob?.status
    prevBatchStatusRef.current = curr ?? null

    if (prev && prev !== curr) {
      if (curr === 'completed') {
        toast.success(`Batch processing completed — ${currentBatchJob?.total_files ?? ''} files processed`)
        if (projectId) fetchProject(projectId)
      } else if (curr === 'error') {
        toast.error('Batch processing finished with errors')
        if (projectId) fetchProject(projectId)
      } else if (curr === 'cancelled') {
        toast('Processing stopped — imported floor plans remain in the list', { icon: '⏹️' })
        if (projectId) fetchProject(projectId)
      }
    }
  }, [currentBatchJob?.status, currentBatchJob?.total_files, projectId, fetchProject])
  
  // Close batch progress modal
  const handleCloseBatchProgress = () => {
    setShowBatchProgress(false)
    // Only clear the job if it's completed or errored
    // Keep it in state if still processing so the indicator can show
    if (currentBatchJob?.status === 'completed' || currentBatchJob?.status === 'error' || currentBatchJob?.status === 'cancelled') {
      clearBatchJob()
    }
  }
  
  // Check if there's an active job running in the background
  const hasActiveBackgroundJob = currentBatchJob && 
    !showBatchProgress && 
    (currentBatchJob.status === 'pending' || currentBatchJob.status === 'processing')
  
  // Start editing project name
  const handleStartEditName = () => {
    if (currentProject) {
      setEditedName(currentProject.name)
      setIsEditingName(true)
      setTimeout(() => nameInputRef.current?.focus(), 0)
    }
  }
  
  // Save project name
  const handleSaveName = async () => {
    if (!projectId || !editedName.trim()) {
      setIsEditingName(false)
      return
    }
    
    if (editedName.trim() === currentProject?.name) {
      setIsEditingName(false)
      return
    }
    
    try {
      await updateProject(projectId, { name: editedName.trim() })
      toast.success('Project renamed')
      setIsEditingName(false)
    } catch {
      toast.error('Failed to rename project')
    }
  }
  
  // Handle key press in name input
  const handleNameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSaveName()
    } else if (e.key === 'Escape') {
      setIsEditingName(false)
    }
  }
  
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-sign-500" />
      case 'processing':
        return <Clock className="w-5 h-5 text-sign-400" />
      default:
        return <AlertCircle className="w-5 h-5 text-slate-400" />
    }
  }
  
  const getStatusText = (status: string) => {
    switch (status) {
      case 'completed':
        return 'Completed'
      case 'processing':
        return 'In Progress'
      default:
        return 'Pending'
    }
  }

  const formatProcessingTime = (seconds: number) => {
    if (seconds < 60) return `${seconds.toFixed(1)}s`
    const minutes = Math.floor(seconds / 60)
    const remaining = Math.round(seconds % 60)
    return `${minutes}m ${remaining}s`
  }
  
  if (isLoading && !currentProject) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }
  
  if (!currentProject) {
    return (
      <PageContainer>
        <p className="text-slate-600 dark:text-slate-400 text-center py-20">Project not found</p>
      </PageContainer>
    )
  }
  
  const allFloorsCompleted = currentProject.floorplans?.every(fp => fp.status === 'completed')
  
  return (
    <PageContainer>
      <div className="page-header">
        <Link 
          to="/" 
          className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white mb-4 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Dashboard
        </Link>
        
        <div className="flex items-start justify-between">
          <div>
            {isEditingName ? (
              <div className="flex items-center gap-2">
                <input
                  ref={nameInputRef}
                  type="text"
                  value={editedName}
                  onChange={(e) => setEditedName(e.target.value)}
                  onKeyDown={handleNameKeyDown}
                  onBlur={handleSaveName}
                  className="text-3xl font-display font-bold text-slate-900 dark:text-white bg-transparent border-b-2 border-sign-500 outline-none py-0"
                />
                <button
                  onClick={handleSaveName}
                  className="p-1.5 text-sign-500 hover:text-sign-400 transition-colors"
                >
                  <Check className="w-5 h-5" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2 group">
                <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">{currentProject.name}</h1>
                <button
                  onClick={handleStartEditName}
                  className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 opacity-0 group-hover:opacity-100 transition-all"
                >
                  <Pencil className="w-4 h-4" />
                </button>
              </div>
            )}
            {currentProject.description && (
              <p className="text-slate-600 dark:text-slate-400 mt-1">{currentProject.description}</p>
            )}
          </div>
          
          <div className="flex items-center gap-3">
            <MarkerColorMenu
              colors={markerColors}
              onChange={setMarkerColors}
              variant="toolbar"
            />
            <button
              onClick={() => setShowMembersModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200 rounded-lg transition-colors"
            >
              <Users className="w-4 h-4" />
              Members
            </button>
            
            {currentProject.floorplans && currentProject.floorplans.length > 0 && (
              <Link
                to={`/project/${projectId}/export`}
                className={clsx(
                  'btn flex items-center gap-2',
                  allFloorsCompleted ? 'btn-primary' : 'btn-secondary'
                )}
              >
                <Download className="w-5 h-5" />
                Export Data
              </Link>
            )}
          </div>
        </div>
      </div>
      
      {/* Upload Section */}
      <div className="mb-8">
        {/* Floorplan Upload */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="card p-6"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-sign-500/20 rounded-lg flex items-center justify-center">
                <Layers className="w-5 h-5 text-sign-500" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900 dark:text-white">Floor Plan PDFs</h3>
                <p className="text-sm text-slate-600 dark:text-slate-400">
                  Upload multiple PDFs - auto shape detection & OCR
                </p>
              </div>
            </div>
            <div className="flex gap-1">
              <button
                onClick={() => importTab === 'manual' ? setDetectionMode('fast') : setWatcherMode('fast')}
                className={clsx(
                  'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  (importTab === 'manual' ? detectionMode : watcherMode) === 'fast'
                    ? 'bg-sign-500 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700'
                )}
              >
                Fast
              </button>
              <button
                onClick={() => importTab === 'manual' ? setDetectionMode('accurate') : setWatcherMode('accurate')}
                className={clsx(
                  'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  (importTab === 'manual' ? detectionMode : watcherMode) === 'accurate'
                    ? 'bg-sign-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700'
                )}
              >
                Accurate
              </button>
            </div>
          </div>

          {/* Import Mode Tabs */}
          <div className="flex border-b border-slate-200 dark:border-slate-700">
            <button
              onClick={() => setImportTab('manual')}
              className={clsx(
                'flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
                importTab === 'manual'
                  ? 'border-sign-500 text-sign-600 dark:text-sign-400'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
              )}
            >
              <Upload className="w-4 h-4" />
              Manual Upload
            </button>
            <button
              onClick={() => setImportTab('watcher')}
              className={clsx(
                'flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
                importTab === 'watcher'
                  ? 'border-sign-500 text-sign-600 dark:text-sign-400'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
              )}
            >
              <Eye className="w-4 h-4" />
              Folder Watch
              {watcherStatus?.status === 'running' && (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-sign-500/15 text-sign-700 dark:bg-sign-500/20 dark:text-sign-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-sign-500 animate-pulse" />
                  Running
                </span>
              )}
            </button>
          </div>

          {/* Tab Content */}
          {importTab === 'manual' ? (
            <>
              {/* Manual Upload Zone */}
              <div
                ref={dropZoneRef}
                onDragEnter={handleDragEnter}
                onDragLeave={handleDragLeave}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                className={clsx(
                  'w-full border-2 border-dashed rounded-lg transition-all',
                  isDragging
                    ? 'border-sign-500 bg-sign-500/10 scale-[1.02]'
                    : 'border-slate-300 dark:border-slate-600',
                  isBatchUploading && 'pointer-events-none opacity-50'
                )}
              >
                {isDragging ? (
                  <div className="p-10 text-center">
                    <Upload className="w-10 h-10 mx-auto mb-3 text-sign-500" />
                    <p className="font-medium text-sign-500">Drop PDF files here</p>
                  </div>
                ) : (
                  <button
                    onClick={() => floorplanInputRef.current?.click()}
                    className="flex flex-col items-center gap-2 p-8 w-full hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors rounded-lg cursor-pointer"
                  >
                    <Upload className="w-8 h-8 text-slate-400" />
                    <span className="text-sm font-medium text-slate-600 dark:text-slate-400">Select Files</span>
                    <span className="text-xs text-slate-400 dark:text-slate-500">or drag & drop PDFs</span>
                  </button>
                )}
              </div>

              <input
                ref={floorplanInputRef}
                type="file"
                accept=".pdf"
                multiple
                onChange={handleFileSelect}
                className="hidden"
              />

              {/* Selected Files List */}
              {selectedFiles.length > 0 && (
                <div className="mt-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300">
                      Selected Files ({selectedFiles.length})
                      <span className="ml-2 text-xs font-normal text-slate-500">
                        {(selectedFiles.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1)} MB
                      </span>
                    </h4>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setSelectedFiles([])
                      }}
                      className="text-xs text-slate-500 hover:text-red-500 dark:text-slate-400 dark:hover:text-red-400 transition-colors"
                    >
                      Clear all
                    </button>
                  </div>
                  
                  <div className="space-y-2 max-h-40 overflow-y-auto">
                    {selectedFiles.map((file, index) => (
                      <motion.div
                        key={`${file.name}-${index}`}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        className="flex items-center justify-between p-2 bg-slate-50 dark:bg-slate-800 rounded-lg"
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <FileText className="w-4 h-4 text-red-500 flex-shrink-0" />
                          <span className="text-sm text-slate-700 dark:text-slate-300 truncate" title={file.webkitRelativePath || file.name}>
                            {file.webkitRelativePath || file.name}
                          </span>
                          <span className="text-xs text-slate-500 dark:text-slate-500 flex-shrink-0">
                            {(file.size / 1024 / 1024).toFixed(1)} MB
                          </span>
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            removeFile(index)
                          }}
                          className="p-1 text-slate-400 hover:text-red-500 transition-colors flex-shrink-0"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </motion.div>
                    ))}
                  </div>
                  
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleBatchUpload()
                    }}
                    disabled={isBatchUploading}
                    className="mt-4 w-full btn btn-primary flex items-center justify-center gap-2"
                  >
                    {isBatchUploading ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Processing...
                      </>
                    ) : (
                      <>
                        <Upload className="w-4 h-4" />
                        Upload & Process {selectedFiles.length} File{selectedFiles.length > 1 ? 's' : ''}
                      </>
                    )}
                  </button>
                </div>
              )}
            </>
          ) : (
            /* Folder Watcher Tab Content */
            <div className="space-y-4 pt-1">
              {watcherStatus?.status === 'running' ? (
                <>
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        Watching: <span className="font-mono text-xs">{watcherStatus.watch_folder}</span>
                      </p>
                      <p className="text-xs text-slate-500 mt-1">
                        Mode: {watcherStatus.detection_mode} · Files processed: {watcherStatus.files_processed}
                        {watcherStatus.files_failed > 0 && <span className="text-red-500"> · Failed: {watcherStatus.files_failed}</span>}
                      </p>
                      {watcherStatus.last_error && (
                        <p className="text-xs text-red-500 mt-1">{watcherStatus.last_error}</p>
                      )}
                    </div>
                    <button
                      onClick={async () => {
                        if (!projectId) return
                        await stopWatcher(projectId)
                        toast.success('Folder watcher stopped')
                      }}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                    >
                      <EyeOff className="w-4 h-4" />
                      Stop
                    </button>
                  </div>

                  {watcherStatus.recent_files && watcherStatus.recent_files.length > 0 && (
                    <div className="mt-3 space-y-1.5 max-h-48 overflow-y-auto">
                      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Recent Files</p>
                      {watcherStatus.recent_files.map((f, i) => (
                        <div key={`${f.filename}-${i}`} className="flex items-center gap-2 px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 rounded-lg">
                          <FileText className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
                          <span className="text-xs text-slate-700 dark:text-slate-300 truncate flex-1" title={f.filename}>{f.filename}</span>
                          {f.status === 'completed' ? (
                            <span className="flex items-center gap-1 text-xs text-sign-600 dark:text-sign-400 flex-shrink-0">
                              <CheckCircle className="w-3 h-3" />
                              {f.shapes_detected > 0 ? `${f.shapes_detected} signs` : 'Done'}
                            </span>
                          ) : f.status === 'error' ? (
                            <span className="flex items-center gap-1 text-xs text-red-500 flex-shrink-0" title={f.error}>
                              <AlertCircle className="w-3 h-3" />
                              Failed
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-xs text-sign-500 dark:text-sign-400 flex-shrink-0">
                              <Loader2 className="w-3 h-3 animate-spin" />
                              {f.status === 'converting' ? 'Converting' :
                               f.status === 'detecting' ? 'Detecting' :
                               f.status === 'ocr' ? 'OCR' : 'Pending'}
                              <span className="text-slate-400 ml-0.5">{f.progress}%</span>
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="space-y-3">
                  {/* Selected folder display */}
                  {watcherFolder ? (
                    <div className="flex items-center gap-2 p-2.5 bg-sign-500/10 border border-sign-500/30 rounded-lg">
                      <FolderOpen className="w-4 h-4 text-sign-500 flex-shrink-0" />
                      <span className="text-sm text-slate-700 dark:text-slate-300 font-mono truncate flex-1" title={watcherFolder}>{watcherFolder}</span>
                      <button
                        onClick={() => setWatcherFolder('')}
                        className="text-xs text-slate-400 hover:text-red-500 transition-colors flex-shrink-0"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500 dark:text-slate-400">Select a folder to watch for new PDF files:</p>
                  )}

                  {/* Quick access shortcuts */}
                  <div className="flex gap-1.5">
                    {[
                      { label: 'Desktop', path: '~/Desktop' },
                      { label: 'Downloads', path: '~/Downloads' },
                      { label: 'Documents', path: '~/Documents' },
                    ].map((shortcut) => (
                      <button
                        key={shortcut.path}
                        onClick={async () => {
                          try {
                            const data = await browseFolders(shortcut.path)
                            setFolderBrowser(data)
                          } catch { toast.error('Cannot access folder') }
                        }}
                        className={clsx(
                          'px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                          folderBrowser?.current_path?.endsWith(shortcut.label)
                            ? 'bg-sign-500/15 text-sign-600 dark:text-sign-400 border border-sign-500/30'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700'
                        )}
                      >
                        {shortcut.label}
                      </button>
                    ))}
                  </div>

                  {/* Folder browser — always visible */}
                  {folderBrowser && (
                    <div className="border border-slate-200 dark:border-slate-700 rounded-lg max-h-52 overflow-y-auto">
                      <div className="flex items-center gap-2 px-3 py-2 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 sticky top-0">
                        {folderBrowser.parent_path && (
                          <button
                            onClick={async () => {
                              const data = await browseFolders(folderBrowser.parent_path!)
                              setFolderBrowser(data)
                            }}
                            className="text-xs text-sign-500 hover:underline flex-shrink-0"
                          >← Up</button>
                        )}
                        <span className="text-xs text-slate-500 font-mono truncate">{folderBrowser.current_path}</span>
                        <button
                          onClick={() => setWatcherFolder(folderBrowser.current_path)}
                          className={clsx(
                            'ml-auto text-xs font-medium flex-shrink-0 transition-colors',
                            watcherFolder === folderBrowser.current_path
                              ? 'text-sign-600 dark:text-sign-400'
                              : 'text-sign-600 hover:underline'
                          )}
                        >
                          {watcherFolder === folderBrowser.current_path ? '✓ Selected' : 'Select This'}
                        </button>
                      </div>
                      {folderBrowser.folders.length === 0 ? (
                        <p className="px-3 py-2 text-xs text-slate-400">No subfolders</p>
                      ) : (
                        folderBrowser.folders.map((f) => (
                          <button
                            key={f.path}
                            onClick={async () => {
                              const data = await browseFolders(f.path)
                              setFolderBrowser(data)
                            }}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors text-left"
                          >
                            <FolderOpen className="w-3.5 h-3.5 text-sign-500 flex-shrink-0" />
                            {f.name}
                          </button>
                        ))
                      )}
                    </div>
                  )}

                  <button
                    onClick={async () => {
                      if (!projectId || !watcherFolder.trim()) {
                        toast.error('Please select a folder')
                        return
                      }
                      try {
                        await startWatcher(projectId, watcherFolder.trim(), watcherMode, markerColors)
                        toast.success('Folder watcher started')
                      } catch {
                        toast.error('Failed to start watcher')
                      }
                    }}
                    disabled={!watcherFolder.trim()}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-sign-500 text-white rounded-lg hover:bg-sign-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium"
                  >
                    <Eye className="w-4 h-4" />
                    Start Watching
                  </button>
                </div>
              )}

              <p className="text-xs text-slate-400 dark:text-slate-500">
                Place PDF files into the watched folder and they will be automatically imported and processed. Processed files are moved to a "processed" subfolder.
              </p>
            </div>
          )}

          {/* Watcher status bar — visible on Manual Upload tab when watcher is running */}
          {importTab === 'manual' && watcherStatus?.status === 'running' && (
            <div className="mt-3 px-3 py-2 bg-sign-500/10 dark:bg-sign-500/10 border border-sign-200 dark:border-sign-800/40 rounded-lg">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-sign-500 animate-pulse flex-shrink-0" />
                  <span className="text-xs text-sign-700 dark:text-sign-400 truncate">
                    Watching: <span className="font-mono">{watcherStatus.watch_folder}</span>
                  </span>
                  <span className="text-xs text-sign-600/70 dark:text-sign-500/70 flex-shrink-0">
                    · {watcherStatus.files_processed} processed
                    {watcherStatus.files_failed > 0 && <span className="text-red-500"> · {watcherStatus.files_failed} failed</span>}
                  </span>
                </div>
                <button
                  onClick={() => setImportTab('watcher')}
                  className="text-xs text-sign-600 dark:text-sign-400 hover:underline flex-shrink-0 ml-2"
                >
                  View details →
                </button>
              </div>
              {watcherStatus.recent_files && watcherStatus.recent_files.some(f => f.status !== 'completed' && f.status !== 'error') && (
                <div className="mt-1.5 flex items-center gap-2 text-xs text-sign-500 dark:text-sign-400">
                  <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" />
                  {watcherStatus.recent_files.find(f => f.status !== 'completed' && f.status !== 'error')?.filename}
                  {' — '}
                  {(() => {
                    const f = watcherStatus.recent_files!.find(f => f.status !== 'completed' && f.status !== 'error')
                    if (!f) return ''
                    return f.status === 'converting' ? 'Converting' : f.status === 'detecting' ? 'Detecting' : f.status === 'ocr' ? 'OCR' : 'Pending'
                  })()}
                </div>
              )}
            </div>
          )}
        </motion.div>
      </div>

      {/* Info about sign table */}
      {currentProject.floorplans && currentProject.floorplans.length > 0 && (
        <div className="mb-6 p-4 bg-sign-500/10 border border-sign-500/30 rounded-lg">
          <p className="text-sm text-sign-700 dark:text-sign-300">
            <span className="font-medium">Tip:</span> After processing floor plans, visit the Export page to view the auto-generated sign table with all extracted data.
          </p>
        </div>
      )}
      
      {/* Floor Plans List */}
      {currentProject.floorplans && currentProject.floorplans.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
              Floor Plans ({currentProject.floorplans.length})
            </h2>
            <div className="flex items-center gap-2">
              {pendingFloorplanCount > 0 && !isBatchUploading && !hasActiveBackgroundJob && (
                <button
                  onClick={handleResumeProcessing}
                  className="btn btn-primary text-xs flex items-center gap-1.5"
                >
                  <Play className="w-3.5 h-3.5" />
                  Resume Processing ({pendingFloorplanCount})
                </button>
              )}
              <button
              onClick={async () => {
                if (!projectId) return
                setIsReExtractingTitles(true)
                try {
                  const res = await api.post(`/projects/${projectId}/re-extract-titles`)
                  const { updated } = res.data
                  if (updated.length > 0) {
                    toast.success(`Updated ${updated.length} floor title(s)`)
                    fetchProject(projectId)
                  } else {
                    toast('No title changes detected', { icon: 'ℹ️' })
                  }
                } catch {
                  toast.error('Failed to re-extract titles')
                } finally {
                  setIsReExtractingTitles(false)
                }
              }}
              disabled={isReExtractingTitles}
              className="btn btn-secondary text-xs flex items-center gap-1.5"
            >
              {isReExtractingTitles ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <FileText className="w-3.5 h-3.5" />
              )}
              Re-extract Titles
            </button>
            </div>
          </div>
          
          <div className="space-y-3">
            {currentProject.floorplans.map((floorplan, index) => (
              <motion.div
                key={floorplan.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.1 * index }}
                className="card p-4 hover:border-slate-300 dark:hover:border-slate-600 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 bg-sign-100 dark:bg-sign-900/40 rounded-lg flex items-center justify-center text-sign-700 dark:text-sign-400 font-mono font-bold">
                      {floorplan.floor_number}
                    </div>
                    
                    <div>
                      <h3 className="font-medium text-slate-900 dark:text-white">{floorplan.floor_name}</h3>
                      <div className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-400 mt-0.5">
                        {floorplan.pdf_filename && (
                          <span className="truncate max-w-[240px]" title={floorplan.pdf_filename}>
                            {floorplan.pdf_filename}
                          </span>
                        )}
                        <span>{floorplan.data_count} items extracted</span>
                        {floorplan.shape_type && (
                          <span className="px-2 py-0.5 bg-slate-200 dark:bg-slate-700 rounded text-slate-700 dark:text-slate-300 text-xs">
                            {floorplan.shape_type}s
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                      {floorplan.status === 'completed' && floorplan.processing_time_seconds != null && (
                        <span
                          className="text-xs font-mono text-slate-500 dark:text-slate-400"
                          title="Recognition time"
                        >
                          {formatProcessingTime(floorplan.processing_time_seconds)}
                        </span>
                      )}
                      {getStatusIcon(floorplan.status)}
                      <span className="text-sm text-slate-700 dark:text-slate-300">
                        {getStatusText(floorplan.status)}
                      </span>
                    </div>
                    
                    <Link
                      to={`/project/${projectId}/floor/${floorplan.id}`}
                      className="btn btn-secondary flex items-center gap-2 text-sm"
                    >
                      {floorplan.status === 'completed' ? 'Review' : 'Process'}
                      <ArrowRight className="w-4 h-4" />
                    </Link>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>
      )}
      
      {/* Empty State for Floorplans */}
      {(!currentProject.floorplans || currentProject.floorplans.length === 0) && (
        <div className="text-center py-12 text-slate-600 dark:text-slate-400">
          <Layers className="w-12 h-12 mx-auto mb-4 opacity-50" />
          <p>Upload a floor plan PDF to get started</p>
        </div>
      )}
      
      {/* Project Members Modal */}
      {currentProject && projectId && (
        <ProjectMembersModal
          projectId={projectId}
          projectName={currentProject.name}
          isOpen={showMembersModal}
          onClose={() => setShowMembersModal(false)}
        />
      )}
      
      {/* Batch Upload Progress Modal */}
      <BatchUploadProgress
        job={currentBatchJob}
        isOpen={showBatchProgress}
        onClose={handleCloseBatchProgress}
        onPoll={handlePollStatus}
        onCancel={handleCancelBatch}
        onCancelFile={handleCancelBatchFile}
      />
      
      {/* Floating Processing Indicator - shows when dialog is closed but job is running */}
      {hasActiveBackgroundJob && (
        <motion.button
          initial={{ opacity: 0, y: 20, scale: 0.9 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 20, scale: 0.9 }}
          onClick={() => setShowBatchProgress(true)}
          className="fixed bottom-6 right-6 z-40 flex items-center gap-3 px-4 py-3 bg-sign-600 hover:bg-sign-500 text-white rounded-full shadow-lg shadow-sign-500/30 transition-colors cursor-pointer"
        >
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm font-medium">
            Processing {currentBatchJob.total_files} file{currentBatchJob.total_files > 1 ? 's' : ''}...
          </span>
          <div className="w-8 h-8 bg-white/20 rounded-full flex items-center justify-center">
            <span className="text-xs font-bold">
              {Math.round((currentBatchJob.files.reduce((sum, f) => sum + f.progress, 0) / currentBatchJob.total_files))}%
            </span>
          </div>
        </motion.button>
      )}
    </PageContainer>
  )
}

