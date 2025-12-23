import { useEffect, useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { 
  Upload, 
  Layers,
  ArrowRight,
  CheckCircle,
  Clock,
  AlertCircle,
  Download,
  ChevronLeft,
  Users
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import ProjectMembersModal from '../components/ProjectMembersModal'
import toast from 'react-hot-toast'
import clsx from 'clsx'

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { currentProject, fetchProject, uploadFloorplan, isLoading } = useProjectStore()
  const [uploadingFloorplan, setUploadingFloorplan] = useState(false)
  const [showMembersModal, setShowMembersModal] = useState(false)
  
  const floorplanInputRef = useRef<HTMLInputElement>(null)
  
  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
    }
  }, [projectId, fetchProject])
  
  const handleFloorplanUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !projectId) return
    
    setUploadingFloorplan(true)
    try {
      await uploadFloorplan(projectId, file)
      toast.success('Floor plan uploaded successfully!')
    } catch {
      toast.error('Failed to upload floor plan')
    }
    setUploadingFloorplan(false)
    e.target.value = ''
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
            <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">{currentProject.name}</h1>
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
      <div className="max-w-xl mb-8">
        {/* Floorplan Upload */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="card p-6"
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 bg-blue-500/20 rounded-lg flex items-center justify-center">
              <Layers className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-900 dark:text-white">Floor Plan PDF</h3>
              <p className="text-sm text-slate-600 dark:text-slate-400">Upload multi-page floor plans</p>
            </div>
          </div>
          
          <button
            onClick={() => floorplanInputRef.current?.click()}
            disabled={uploadingFloorplan}
            className="w-full p-6 border-2 border-dashed border-slate-300 dark:border-slate-600 rounded-lg hover:border-sign-500 hover:bg-sign-500/5 transition-colors group"
          >
            {uploadingFloorplan ? (
              <div className="w-6 h-6 border-2 border-slate-500/30 border-t-slate-400 rounded-full animate-spin mx-auto" />
            ) : (
              <>
                <Upload className="w-8 h-8 text-slate-400 group-hover:text-sign-500 dark:group-hover:text-sign-400 mx-auto mb-2 transition-colors" />
                <p className="text-slate-600 group-hover:text-slate-900 dark:text-slate-400 dark:group-hover:text-white transition-colors">
                  Click to upload floor plan PDF
                </p>
                <p className="text-sm text-slate-500 dark:text-slate-500 mt-1">Multi-page PDF supported</p>
              </>
            )}
          </button>
          
          <input
            ref={floorplanInputRef}
            type="file"
            accept=".pdf"
            onChange={handleFloorplanUpload}
            className="hidden"
          />
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
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white mb-4">
            Floor Plans ({currentProject.floorplans.length})
          </h2>
          
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
    </div>
  )
}

