import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useWaStore } from '../../store/waStore'
import WaStatusBadge from '../../components/wa/StatusBadge'
import { FolderOpen, ArrowRight, Calendar, Inbox } from 'lucide-react'

export default function WaProjectsPage() {
  const { projects, fetchProjects, loading } = useWaStore()

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900 dark:text-white">WA Projects</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            {projects.length} active project{projects.length !== 1 ? 's' : ''}
          </p>
        </div>
        <Link to="/wa/admin/projects" className="btn btn-primary text-sm px-4 py-2">+ New Project</Link>
      </div>

      {loading && projects.length === 0 ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <FolderOpen className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
          <p className="text-slate-500 dark:text-slate-400">No projects yet</p>
          <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">Create your first project to get started</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((project) => (
            <div key={project.id} className="group card hover:border-slate-400 dark:hover:border-slate-500 transition-colors p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-slate-900 dark:text-white truncate">{project.name}</h3>
                  <p className="text-xs font-mono text-slate-500 dark:text-slate-400 mt-0.5">{project.code}</p>
                </div>
              </div>

              {project.location && (
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-3 truncate">{project.location}</p>
              )}

              <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 mb-4">
                <span className="flex items-center gap-1"><Inbox className="h-3 w-3" />{project.totalRecords ?? 0} records</span>
                {(project.todayRecords ?? 0) > 0 && (
                  <span className="flex items-center gap-1 text-sign-600 dark:text-sign-400 font-medium">
                    <Calendar className="h-3 w-3" />+{project.todayRecords} today
                  </span>
                )}
              </div>

              <div className="flex items-center justify-between pt-3 border-t border-slate-200 dark:border-slate-700">
                <WaStatusBadge status={project.status} size="sm" />
                <Link to={`/wa/projects/${project.id}`} className="inline-flex items-center gap-1 text-xs font-medium text-sign-600 hover:text-sign-500 dark:text-sign-400">
                  Open <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
