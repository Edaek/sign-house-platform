import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Search, RefreshCw, ChevronDown } from 'lucide-react'
import clsx from 'clsx'
import { useAuthStore } from '../store/authStore'
import PageContainer from '../components/PageContainer'
import {
  formatAuditDetailValue,
  formatAuditTimestamp,
  formatResourceType,
  formatStatusLabel,
  getActionColor,
} from '../lib/theme'
import api from '../lib/api'

interface AuditLog {
  id: string
  user_id: string
  username?: string
  action: string
  resource_type?: string
  resource_id?: string
  details: Record<string, unknown>
  ip_address?: string
  timestamp: string
}

function EmptyCell() {
  return <span className="text-slate-400 dark:text-slate-500">—</span>
}

function AuditDetails({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details)
  if (entries.length === 0) return <EmptyCell />

  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-sm font-medium text-sign-600 transition-colors hover:text-sign-500 dark:text-sign-400 dark:hover:text-sign-300 [&::-webkit-details-marker]:hidden">
        <ChevronDown className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-180" />
        View details
      </summary>
      <dl className="mt-2 space-y-1.5 rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/60">
        {entries.map(([key, value]) => (
          <div key={key} className="grid grid-cols-[minmax(5rem,auto)_1fr] gap-x-3 gap-y-0.5 text-xs">
            <dt className="font-medium text-slate-500 dark:text-slate-400">
              {formatStatusLabel(key)}
            </dt>
            <dd className="break-all font-mono text-slate-700 dark:text-slate-300">
              {formatAuditDetailValue(value)}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  )
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
        <div className="mb-2 flex items-center gap-3">
          <FileText className="h-8 w-8 text-sign-500" />
          <h1 className="page-title">Audit Logs</h1>
        </div>
        <p className="page-subtitle">Track all system actions and user activities</p>
      </div>

      <div className="card mb-6 p-6">
        <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Action
            </label>
            <input
              type="text"
              placeholder="Login, Project Created…"
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
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
            <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
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
            <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
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
          <button onClick={fetchLogs} className="btn btn-secondary p-2" aria-label="Refresh">
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
                    <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Timestamp
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      User
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Action
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Resource
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Details
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      IP Address
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                  {logs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-50 dark:hover:bg-slate-700/30">
                      <td className="whitespace-nowrap px-6 py-4">
                        <time
                          dateTime={log.timestamp}
                          className="text-sm tabular-nums text-slate-700 dark:text-slate-200"
                        >
                          {formatAuditTimestamp(log.timestamp)}
                        </time>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-sm font-medium text-slate-900 dark:text-white">
                          {log.username || 'Unknown'}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={clsx(
                            'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium',
                            getActionColor(log.action),
                          )}
                        >
                          {formatStatusLabel(log.action)}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        {log.resource_type ? (
                          <div className="space-y-1">
                            <span className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200">
                              {formatResourceType(log.resource_type)}
                            </span>
                            {log.resource_id && (
                              <div
                                className="font-mono text-[11px] text-slate-500 dark:text-slate-400"
                                title={log.resource_id}
                              >
                                {log.resource_id}
                              </div>
                            )}
                          </div>
                        ) : (
                          <EmptyCell />
                        )}
                      </td>
                      <td className="max-w-xs px-6 py-4">
                        <AuditDetails details={log.details} />
                      </td>
                      <td className="px-6 py-4">
                        {log.ip_address ? (
                          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                            {log.ip_address}
                          </code>
                        ) : (
                          <EmptyCell />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-slate-200 px-6 py-4 dark:border-slate-700">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="btn btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="text-sm tabular-nums text-slate-600 dark:text-slate-400">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="btn btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
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
