import { useEffect, useState, useCallback } from 'react'
import api from '../../lib/api'
import toast from 'react-hot-toast'
import { Plus } from 'lucide-react'

interface WaUser {
  id: string
  username: string
  email: string
  role: string
  is_active: boolean
  created_at: string
}

export default function WaUsersPage() {
  const [users, setUsers] = useState<WaUser[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [creating, setCreating] = useState(false)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/admin/users', { params: { per_page: 100 } })
      setUsers(data.users || [])
    } catch {
      toast.error('Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadUsers() }, [loadUsers])

  async function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    setCreating(true)
    try {
      await api.post('/admin/users', {
        email: form.get('email'),
        password: form.get('password'),
        name: form.get('name'),
        role: form.get('role'),
      })
      toast.success('User created')
      setDialogOpen(false)
      loadUsers()
    } catch (err: any) {
      toast.error(err?.response?.data?.error || 'Failed to create user')
    } finally {
      setCreating(false)
    }
  }

  async function handleRoleChange(userId: string, newRole: string) {
    try {
      await api.put(`/admin/users/${userId}/role`, { role: newRole })
      toast.success('Role updated')
      loadUsers()
    } catch {
      toast.error('Failed to update role')
    }
  }

  async function handleToggleStatus(userId: string, isActive: boolean) {
    try {
      await api.put(`/admin/users/${userId}/status`, { is_active: !isActive })
      toast.success(isActive ? 'User deactivated' : 'User activated')
      loadUsers()
    } catch (err: any) {
      toast.error(err?.response?.data?.error || 'Failed to update status')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900 dark:text-white">User Management</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">{users.length} users</p>
        </div>
        <button onClick={() => setDialogOpen(true)} className="btn btn-primary text-sm px-3 py-1.5 flex items-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />New User
        </button>
      </div>

      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-md mx-4">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Create User</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Name</label>
                <input name="name" required className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Email</label>
                <input name="email" type="email" required className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Password</label>
                <input name="password" type="password" required minLength={6} className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Role</label>
                <select name="role" className="input w-full">
                  <option value="user">User</option>
                  <option value="manager">Manager</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div className="flex gap-2 pt-2">
                <button type="button" onClick={() => setDialogOpen(false)} className="btn btn-secondary flex-1">Cancel</button>
                <button type="submit" disabled={creating} className="btn btn-primary flex-1">
                  {creating ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-800/50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Name</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Email</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Role</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Status</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {users.map((user) => {
                return (
                  <tr key={user.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                    <td className="px-4 py-2.5 font-medium text-slate-800 dark:text-slate-200">{user.username}</td>
                    <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">{user.email}</td>
                    <td className="px-4 py-2.5">
                      <select
                        value={user.role}
                        onChange={(e) => handleRoleChange(user.id, e.target.value)}
                        className="text-xs rounded-md border border-slate-200 dark:border-slate-700 bg-transparent px-2 py-1"
                      >
                        <option value="user">User</option>
                        <option value="manager">Manager</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        user.is_active
                          ? 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300'
                          : 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300'
                      }`}>
                        {user.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={() => handleToggleStatus(user.id, user.is_active)}
                        className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                      >
                        {user.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
