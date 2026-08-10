import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Search, RefreshCw } from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import PageContainer from '../components/PageContainer'
import { getActionColor } from '../lib/theme'
import api from '../lib/api'

interface AuditLog {
  id: string
  user_id: string
  username?: string
  action: string
  resource_type?: string
  resource_id?: string
  details: Record<string, any>
  ip_address?: string
  timestamp: string
}

export default function AuditLogsPage() {
  const navigate = useNavigate()
  const { isAdmin } = useAuthStore()
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [loading, setLoading] = useState(true)
  const [actionFilter, setActionFilter] = useState('')
  const [resourceFilter, setResourceFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)

  // Redirect if not admin
  useEffect(() => {
    if (!isAdmin()) {
      navigate('/dashboard')
    }
  }, [isAdmin, navigate])

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: '50',
      })
      if (actionFilter) params.append('action', actionFilter)
      if (resourceFilter) params.append('resource_type', resourceFilter)
      if (startDate) params.append('start_date', new Date(startDate).toISOString())
      if (endDate) params.append('end_date', new Date(endDate).toISOString())

      const response = await api.get(`/admin/audit-logs?${params}`)
      setLogs(response.data.logs)
      setTotalPages(response.data.total_pages)
    } catch (error) {
      console.error('Failed to fetch audit logs:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isAdmin()) {
      fetchLogs()
    }
  }, [page, isAdmin])

  const handleFilter = () => {
    setPage(1)
    fetchLogs()
  }

  const handleReset = () => {
    setActionFilter('')
    setResourceFilter('')
    setStartDate('')
    setEndDate('')
    setPage(1)
    setTimeout(fetchLogs, 0)
  }

  if (!isAdmin()) {
    return null
  }

  return (
    <PageContainer>
      <div className="page-header">
        <div className="flex items-center gap-3 mb-2">
          <FileText className="h-8 w-8 text-sign-500" />
          <h1 className="page-title">
            Audit Logs
          </h1>
        </div>
        <p className="page-subtitle">
          Track all system actions and user activities
        </p>
      </div>

      <div className="card p-6 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              Action
            </label>
            <input
              type="text"
              placeholder="e.g., login, project_created"
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              Resource Type
            </label>
            <select
              value={resourceFilter}
              onChange={(e) => setResourceFilter(e.target.value)}
              className="input"
            >
              <option value="">All Types</option>
              <option value="user">User</option>
              <option value="project">Project</option>
              <option value="floorplan">Floorplan</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              Start Date
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              End Date
            </label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="input"
            />
          </div>
        </div>
        <div className="flex gap-4">
          <button onClick={handleFilter} className="btn btn-primary">
            <Search className="h-4 w-4" />
            Apply Filters
          </button>
          <button onClick={handleReset} className="btn btn-secondary">
            Reset
          </button>
          <button onClick={fetchLogs} className="btn btn-secondary p-2">
            <RefreshCw className="h-5 w-5" />
          </button>
        </div>
      </div>

      <div className="card overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-500 dark:text-slate-400">
            Loading audit logs...
          </div>
        ) : logs.length === 0 ? (
          <div className="p-8 text-center text-slate-500 dark:text-slate-400">
            No audit logs found
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-50 dark:bg-slate-700/50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      Timestamp
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      User
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      Action
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      Resource
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      Details
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      IP Address
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                  {logs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-50 dark:hover:bg-slate-700/30">
                      <td className="px-6 py-4 text-sm text-slate-900 dark:text-white whitespace-nowrap">
                        {new Date(log.timestamp).toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-sm text-slate-900 dark:text-white">
                        {log.username || 'Unknown'}
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={`text-xs px-2 py-1 rounded-full font-medium ${getActionColor(log.action)}`}
                        >
                          {log.action}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-sm text-slate-900 dark:text-white">
                        {log.resource_type ? (
                          <div>
                            <div className="font-medium">{log.resource_type}</div>
                            {log.resource_id && (
                              <div className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                                {log.resource_id.substring(0, 8)}...
                              </div>
                            )}
                          </div>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="px-6 py-4 text-sm text-slate-600 dark:text-slate-400 max-w-xs truncate">
                        {Object.keys(log.details).length > 0 ? (
                          <details className="cursor-pointer">
                            <summary className="hover:text-sign-600 dark:hover:text-sign-400">View details</summary>
                            <pre className="mt-2 text-xs bg-slate-100 dark:bg-slate-900 p-2 rounded overflow-x-auto">
                              {JSON.stringify(log.details, null, 2)}
                            </pre>
                          </details>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="px-6 py-4 text-sm text-slate-600 dark:text-slate-400 font-mono">
                        {log.ip_address || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="btn btn-secondary disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <span className="text-sm text-slate-600 dark:text-slate-400">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="btn btn-secondary disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </PageContainer>
  )
}

