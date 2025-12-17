import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Users, Search, RefreshCw } from 'lucide-react'
import { useAuthStore, UserRole } from '../store/authStore'
import RoleBadge from '../components/RoleBadge'
import api from '../lib/api'

interface UserData {
  id: string
  username: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
  project_count: number
}

export default function AdminPage() {
  const navigate = useNavigate()
  const { user, isAdmin } = useAuthStore()
  const [users, setUsers] = useState<UserData[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [updatingUser, setUpdatingUser] = useState<string | null>(null)

  // Redirect if not admin
  useEffect(() => {
    if (!isAdmin()) {
      navigate('/dashboard')
    }
  }, [isAdmin, navigate])

  const fetchUsers = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: '20',
      })
      if (search) params.append('search', search)
      if (roleFilter !== 'all') params.append('role', roleFilter)
      if (statusFilter !== 'all') params.append('status', statusFilter)

      const response = await api.get(`/admin/users?${params}`)
      setUsers(response.data.users)
      setTotalPages(response.data.total_pages)
    } catch (error) {
      console.error('Failed to fetch users:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isAdmin()) {
      fetchUsers()
    }
  }, [page, roleFilter, statusFilter, isAdmin])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    fetchUsers()
  }

  const handleRoleChange = async (userId: string, newRole: UserRole) => {
    if (!window.confirm(`Are you sure you want to change this user's role to ${newRole}?`)) {
      return
    }

    setUpdatingUser(userId)
    try {
      await api.put(`/admin/users/${userId}/role`, { role: newRole })
      await fetchUsers()
    } catch (error: any) {
      alert(error.response?.data?.error || 'Failed to update role')
    } finally {
      setUpdatingUser(null)
    }
  }

  const handleStatusChange = async (userId: string, isActive: boolean) => {
    if (!window.confirm(`Are you sure you want to ${isActive ? 'activate' : 'deactivate'} this user?`)) {
      return
    }

    setUpdatingUser(userId)
    try {
      await api.put(`/admin/users/${userId}/status`, { is_active: isActive })
      await fetchUsers()
    } catch (error: any) {
      alert(error.response?.data?.error || 'Failed to update status')
    } finally {
      setUpdatingUser(null)
    }
  }

  if (!isAdmin()) {
    return null
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <Users className="h-8 w-8 text-purple-600 dark:text-purple-400" />
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            User Management
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          Manage users, assign roles, and control access
        </p>
      </div>

      {/* Filters */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm p-6 mb-6">
        <form onSubmit={handleSearch} className="flex flex-col md:flex-row gap-4">
          <div className="flex-1">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
              <input
                type="text"
                placeholder="Search by username or email..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:text-white"
              />
            </div>
          </div>
          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value)
              setPage(1)
            }}
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:text-white"
          >
            <option value="all">All Roles</option>
            <option value="admin">Admin</option>
            <option value="manager">Manager</option>
            <option value="user">User</option>
          </select>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value)
              setPage(1)
            }}
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:text-white"
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
          <button
            type="submit"
            className="px-6 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors"
          >
            Search
          </button>
          <button
            type="button"
            onClick={() => fetchUsers()}
            className="px-4 py-2 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-lg transition-colors"
          >
            <RefreshCw className="h-5 w-5" />
          </button>
        </form>
      </div>

      {/* Users Table */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500 dark:text-gray-400">
            Loading users...
          </div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center text-gray-500 dark:text-gray-400">
            No users found
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-gray-700">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      User
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      Role
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      Projects
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      Created
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {users.map((u) => (
                    <tr key={u.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                      <td className="px-6 py-4">
                        <div>
                          <div className="font-medium text-gray-900 dark:text-white">
                            {u.username}
                            {u.id === user?.id && (
                              <span className="ml-2 text-xs text-gray-500">(You)</span>
                            )}
                          </div>
                          <div className="text-sm text-gray-500 dark:text-gray-400">
                            {u.email}
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <select
                          value={u.role}
                          onChange={(e) => handleRoleChange(u.id, e.target.value as UserRole)}
                          disabled={updatingUser === u.id || u.id === user?.id}
                          className="text-sm border border-gray-300 dark:border-gray-600 rounded px-2 py-1 dark:bg-gray-700 dark:text-white disabled:opacity-50"
                        >
                          <option value="admin">Admin</option>
                          <option value="manager">Manager</option>
                          <option value="user">User</option>
                        </select>
                      </td>
                      <td className="px-6 py-4">
                        <button
                          onClick={() => handleStatusChange(u.id, !u.is_active)}
                          disabled={updatingUser === u.id || u.id === user?.id}
                          className={`text-sm px-3 py-1 rounded-full font-medium ${
                            u.is_active
                              ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                              : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                          } disabled:opacity-50 hover:opacity-80 transition-opacity`}
                        >
                          {u.is_active ? 'Active' : 'Inactive'}
                        </button>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-900 dark:text-white">
                        {u.project_count}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">
                        {new Date(u.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-6 py-4 text-sm">
                        <RoleBadge role={u.role} size="sm" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-4 py-2 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-4 py-2 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

