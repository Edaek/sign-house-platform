import { useEffect, useState } from 'react'
import { useWaStore } from '../../store/waStore'
import WaStatusBadge from '../../components/wa/StatusBadge'
import toast from 'react-hot-toast'
import { Plus, FolderOpen, Trash2 } from 'lucide-react'

export default function WaManageProjectsPage() {
  const { projects, fetchProjects, createProject, deleteProject, nasStatus, fetchNasStatus } = useWaStore()
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; code: string } | null>(null)
  const [deleteNasFolder, setDeleteNasFolder] = useState(false)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    fetchProjects().then(() => setLoading(false))
    fetchNasStatus()
  }, [fetchProjects, fetchNasStatus])

  async function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    try {
      await createProject({
        code: form.get('code') as string,
        name: form.get('name') as string,
        location: (form.get('location') as string) || undefined,
        stage: form.get('stage') as string,
      })
      toast.success('Project created')
      setDialogOpen(false)
      fetchProjects()
    } catch {
      toast.error('Failed to create project')
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteProject(deleteTarget.id, deleteNasFolder)
      toast.success(`Project ${deleteTarget.code} deleted`)
      setDeleteTarget(null)
      setDeleteNasFolder(false)
      fetchProjects()
    } catch {
      toast.error('Failed to delete project')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">Manage Projects</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">{projects.length} projects</p>
        </div>
        <button onClick={() => setDialogOpen(true)} className="btn btn-primary text-sm px-3 py-1.5 flex items-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />New Project
        </button>
      </div>

      {/* Create dialog */}
      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-md mx-4">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Create Project</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Code (e.g. P-001)</label>
                <input name="code" required placeholder="P-001" className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Name</label>
                <input name="name" required className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Location</label>
                <input name="location" className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Stage</label>
                <select name="stage" className="input w-full">
                  <option value="planning">Planning</option>
                  <option value="active">Active</option>
                  <option value="completed">Completed</option>
                  <option value="hold">On Hold</option>
                </select>
              </div>
              <div className="flex gap-2 pt-2">
                <button type="button" onClick={() => setDialogOpen(false)} className="btn btn-secondary flex-1">Cancel</button>
                <button type="submit" className="btn btn-primary flex-1">Create</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete confirmation dialog */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-md mx-4">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">Delete Project</h2>
            <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
              Are you sure you want to delete project <span className="font-mono font-semibold">{deleteTarget.code}</span>?
              This will also delete all associated records.
            </p>

            {nasStatus?.connected && (
              <label className="flex items-center gap-2 p-3 rounded-lg border border-slate-200 dark:border-slate-700 mb-4 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <input
                  type="checkbox"
                  checked={deleteNasFolder}
                  onChange={(e) => setDeleteNasFolder(e.target.checked)}
                  className="rounded border-slate-300 text-sign-600 focus:ring-sign-500"
                />
                <div>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                    Also delete NAS folder
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Remove the folder and all files from the shared drive
                  </p>
                </div>
              </label>
            )}

            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setDeleteTarget(null); setDeleteNasFolder(false) }}
                className="btn btn-secondary flex-1"
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <FolderOpen className="h-10 w-10 text-slate-300 dark:text-slate-600 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">No projects yet</p>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-800/50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Code</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Name</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Location</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Stage</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Status</th>
                <th className="px-4 py-2.5 w-12"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {projects.map((project) => (
                <tr key={project.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                  <td className="px-4 py-2.5 font-mono font-semibold text-slate-800 dark:text-slate-200">{project.code}</td>
                  <td className="px-4 py-2.5 font-medium text-slate-800 dark:text-slate-200">{project.name}</td>
                  <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">{project.location || '—'}</td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center rounded-md bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs font-medium text-slate-600 dark:text-slate-400">
                      {project.stage}
                    </span>
                  </td>
                  <td className="px-4 py-2.5"><WaStatusBadge status={project.status} size="sm" /></td>
                  <td className="px-4 py-2.5">
                    <button
                      onClick={() => setDeleteTarget({ id: project.id, code: project.code })}
                      className="p-1 text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                      title="Delete project"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
