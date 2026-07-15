import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
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
  FileText,
  X,
  Pencil,
  Check,
  Loader2
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import ProjectMembersModal from '../components/ProjectMembersModal'
import BatchUploadProgress from '../components/BatchUploadProgress'
import api from '../lib/api'
import toast from 'react-hot-toast'
import clsx from 'clsx'

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { 
    currentProject, 
    fetchProject, 
    updateProject,
    uploadFloorplans,
    pollBatchStatus,
    fetchActiveBatchJob,
    currentBatchJob,
    isBatchUploading,
    clearBatchJob,
    isLoading 
  } = useProjectStore()
  const [showMembersModal, setShowMembersModal] = useState(false)
  const [showBatchProgress, setShowBatchProgress] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [isEditingName, setIsEditingName] = useState(false)
  const [editedName, setEditedName] = useState('')
  
  const [isReExtractingTitles, setIsReExtractingTitles] = useState(false)
  const [detectionMode, setDetectionMode] = useState<'fast' | 'accurate'>('accurate')

  const floorplanInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const dropZoneRef = useRef<HTMLDivElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  
  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
      // Check for any active batch jobs when page loads
      fetchActiveBatchJob(projectId)
    }
  }, [projectId, fetchProject, fetchActiveBatchJob])
  
  // Handle file selection from input
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length > 0) {
      setSelectedFiles(prev => [...prev, ...files])
    }
    e.target.value = ''
  }

  // Handle folder selection — auto-start processing immediately
  const handleFolderSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!projectId) return
    const allFiles = Array.from(e.target.files || []).filter(f => f.size > 0)
    e.target.value = ''

    if (allFiles.length === 0) {
      toast.error('The selected folder is empty')
      return
    }

    const nonPdfFiles = allFiles.filter(f => !f.name.toLowerCase().endsWith('.pdf'))
    if (nonPdfFiles.length > 0) {
      const names = nonPdfFiles.slice(0, 5).map(f => f.name).join(', ')
      const more = nonPdfFiles.length > 5 ? ` and ${nonPdfFiles.length - 5} more` : ''
      toast.error(`Folder must contain only PDF files. Found non-PDF: ${names}${more}`)
      return
    }

    allFiles.sort((a, b) =>
      (a.webkitRelativePath || a.name).localeCompare(b.webkitRelativePath || b.name)
    )

    const totalMB = allFiles.reduce((s, f) => s + f.size, 0) / 1024 / 1024
    if (totalMB > 500) {
      toast.error(`Total size ${totalMB.toFixed(0)}MB exceeds 500MB limit.`)
      return
    }

    toast.success(`Found ${allFiles.length} PDF${allFiles.length > 1 ? 's' : ''} — uploading...`)

    try {
      const job = await uploadFloorplans(projectId, allFiles, detectionMode)
      setShowBatchProgress(true)
      toast.success(`Started processing ${job.total_files} files`)
    } catch {
      toast.error('Failed to start folder processing')
    }
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
      const job = await uploadFloorplans(projectId, selectedFiles, detectionMode)
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
      }
    }
  }, [currentBatchJob?.status, currentBatchJob?.total_files, projectId, fetchProject])
  
  // Close batch progress modal
  const handleCloseBatchProgress = () => {
    setShowBatchProgress(false)
    // Only clear the job if it's completed or errored
    // Keep it in state if still processing so the indicator can show
    if (currentBatchJob?.status === 'completed' || currentBatchJob?.status === 'error') {
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
        return <CheckCircle className="w-5 h-5 text-emerald-400" />
      case 'processing':
        return <Clock className="w-5 h-5 text-blue-400" />
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
  
  if (isLoading && !currentProject) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }
  
  if (!currentProject) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <p className="text-slate-600 dark:text-slate-400 text-center py-20">Project not found</p>
      </div>
    )
  }
  
  const allFloorsCompleted = currentProject.floorplans?.every(fp => fp.status === 'completed')
  
  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
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
                  className="p-1.5 text-emerald-500 hover:text-emerald-400 transition-colors"
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
              <div className="w-10 h-10 bg-blue-500/20 rounded-lg flex items-center justify-center">
                <Layers className="w-5 h-5 text-blue-400" />
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
                onClick={() => setDetectionMode('fast')}
                className={clsx(
                  'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  detectionMode === 'fast'
                    ? 'bg-amber-500 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700'
                )}
              >
                Fast
              </button>
              <button
                onClick={() => setDetectionMode('accurate')}
                className={clsx(
                  'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  detectionMode === 'accurate'
                    ? 'bg-emerald-500 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700'
                )}
              >
                Accurate
              </button>
            </div>
          </div>
          
          {/* Upload Zone */}
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
              <div className="grid grid-cols-2 divide-x divide-slate-300 dark:divide-slate-600">
                <button
                  onClick={() => floorplanInputRef.current?.click()}
                  className="flex flex-col items-center gap-2 p-6 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors rounded-l-lg cursor-pointer"
                >
                  <Upload className="w-8 h-8 text-slate-400" />
                  <span className="text-sm font-medium text-slate-600 dark:text-slate-400">Select Files</span>
                  <span className="text-xs text-slate-400 dark:text-slate-500">or drag & drop PDFs</span>
                </button>
                <button
                  onClick={() => folderInputRef.current?.click()}
                  className="flex flex-col items-center gap-2 p-6 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors rounded-r-lg cursor-pointer"
                >
                  <FolderOpen className="w-8 h-8 text-slate-400" />
                  <span className="text-sm font-medium text-slate-600 dark:text-slate-400">Select Folder</span>
                  <span className="text-xs text-slate-400 dark:text-slate-500">auto-process all PDFs</span>
                </button>
              </div>
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
          <input
            ref={folderInputRef}
            type="file"
            {...{ webkitdirectory: '', directory: '' } as any}
            multiple
            onChange={handleFolderSelect}
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
        </motion.div>
      </div>
      
      {/* Info about sign table */}
      {currentProject.floorplans && currentProject.floorplans.length > 0 && (
        <div className="mb-6 p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg">
          <p className="text-sm text-blue-200">
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
                    <div className="w-12 h-12 bg-blueprint-100 dark:bg-blueprint-900 rounded-lg flex items-center justify-center text-blueprint-700 dark:text-blueprint-400 font-mono font-bold">
                      {floorplan.floor_number}
                    </div>
                    
                    <div>
                      <h3 className="font-medium text-slate-900 dark:text-white">{floorplan.floor_name}</h3>
                      <div className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-400 mt-0.5">
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
    </div>
  )
}

