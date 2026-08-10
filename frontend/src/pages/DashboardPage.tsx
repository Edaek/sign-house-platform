import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { 
  Plus, 
  FolderOpen, 
  Clock, 
  Layers,
  ArrowRight,
  Trash2,
  MoreVertical,
  User
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import { useAuthStore } from '../store/authStore'
import PageContainer from '../components/PageContainer'
import StatusBadge from '../components/StatusBadge'
import toast from 'react-hot-toast'

export default function DashboardPage() {
  const { projects, fetchProjects, createProject, deleteProject, isLoading } = useProjectStore()
  const { isManager } = useAuthStore()
  const navigate = useNavigate()
  const [showNewProject, setShowNewProject] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [newProjectDesc, setNewProjectDesc] = useState('')
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  
  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])
  
  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newProjectName.trim()) return
    
    try {
      const project = await createProject(newProjectName, newProjectDesc)
      toast.success('Project created!')
      setShowNewProject(false)
      setNewProjectName('')
      setNewProjectDesc('')
      navigate(`/project/${project.id}`)
    } catch {
      toast.error('Failed to create project')
    }
  }
  
  const handleDeleteProject = async (id: string) => {
    if (!confirm('Are you sure you want to delete this project?')) return
    
    try {
      await deleteProject(id)
      toast.success('Project deleted')
    } catch {
      toast.error('Failed to delete project')
    }
    setOpenMenu(null)
  }
  
  return (
    <PageContainer>
      <div className="flex items-center justify-between page-header">
        <div>
          <h1 className="page-title">Projects</h1>
          <p className="page-subtitle">Manage your floor plan analysis projects</p>
        </div>
        
        <button
          onClick={() => setShowNewProject(true)}
          className="btn btn-primary"
        >
          <Plus className="w-4 h-4" />
          New Project
        </button>
      </div>
      
      {showNewProject && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="card p-6 w-full max-w-md mx-4"
          >
            <h2 className="text-xl font-display font-semibold text-slate-900 dark:text-white mb-4">
              Create New Project
            </h2>
            
            <form onSubmit={handleCreateProject} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                  Project Name
                </label>
                <input
                  type="text"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  className="input"
                  placeholder="e.g., Building A Floor Plans"
                  required
                  autoFocus
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                  Description (optional)
                </label>
                <textarea
                  value={newProjectDesc}
                  onChange={(e) => setNewProjectDesc(e.target.value)}
                  className="input min-h-[80px] resize-none"
                  placeholder="Brief description of this project..."
                />
              </div>
              
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowNewProject(false)}
                  className="btn btn-secondary flex-1"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary flex-1"
                  disabled={!newProjectName.trim()}
                >
                  Create Project
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
      
      {isLoading && projects.length === 0 && (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      )}
      
      {!isLoading && projects.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="empty-state"
        >
          <div className="empty-state-icon">
            <FolderOpen className="w-8 h-8 text-slate-400 dark:text-slate-500" />
          </div>
          <h2 className="empty-state-title">No projects yet</h2>
          <p className="empty-state-desc">
            Create your first project to start analyzing floor plans
          </p>
          <button
            onClick={() => setShowNewProject(true)}
            className="btn btn-primary"
          >
            <Plus className="w-4 h-4" />
            Create First Project
          </button>
        </motion.div>
      )}
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {projects.map((project, index) => (
          <motion.div
            key={project.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05 }}
            className="card group hover:border-sign-500/30 dark:hover:border-sign-500/20 transition-colors"
          >
            <div className="p-5">
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-semibold text-slate-900 dark:text-white truncate group-hover:text-sign-600 dark:group-hover:text-sign-400 transition-colors">
                    {project.name}
                  </h3>
                  {project.description && (
                    <p className="text-slate-600 dark:text-slate-400 text-sm mt-1 line-clamp-2">
                      {project.description}
                    </p>
                  )}
                  {isManager() && (project as any).owner_username && (
                    <div className="flex items-center gap-1 mt-2 text-xs text-slate-500 dark:text-slate-400">
                      <User className="w-3 h-3" />
                      <span>{(project as any).owner_username}</span>
                    </div>
                  )}
                </div>
                
                <div className="relative ml-2">
                  <button
                    onClick={(e) => {
                      e.preventDefault()
                      setOpenMenu(openMenu === project.id ? null : project.id)
                    }}
                    className="btn btn-ghost p-2"
                  >
                    <MoreVertical className="w-4 h-4" />
                  </button>
                  
                  {openMenu === project.id && (
                    <div className="absolute right-0 top-full mt-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl z-10 py-1 min-w-[140px]">
                      <button
                        onClick={() => handleDeleteProject(project.id)}
                        className="w-full px-4 py-2 text-left text-red-500 dark:text-red-400 hover:bg-slate-100 dark:hover:bg-slate-700 flex items-center gap-2 text-sm"
                      >
                        <Trash2 className="w-4 h-4" />
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
              
              <div className="flex items-center gap-4 text-sm text-slate-600 dark:text-slate-400 mb-4">
                <div className="flex items-center gap-1.5">
                  <Layers className="w-4 h-4" />
                  <span>{project.floorplan_count} floor{project.floorplan_count !== 1 ? 's' : ''}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Clock className="w-4 h-4" />
                  <span>{new Date(project.updated_at).toLocaleDateString()}</span>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <StatusBadge status={project.status} />
                
                <Link
                  to={`/project/${project.id}`}
                  className="flex items-center gap-1 text-sign-600 hover:text-sign-500 dark:text-sign-400 dark:hover:text-sign-300 font-medium text-sm transition-colors"
                >
                  Open
                  <ArrowRight className="w-4 h-4" />
                </Link>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </PageContainer>
  )
}
