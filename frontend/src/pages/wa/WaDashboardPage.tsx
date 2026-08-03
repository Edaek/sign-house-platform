import { useEffect } from 'react'
import { useWaStore } from '../../store/waStore'
import WaMetricCard from '../../components/wa/MetricCard'
import WaStatusBadge from '../../components/wa/StatusBadge'
import { Inbox, Clock, Eye, CheckCircle2, AlertTriangle } from 'lucide-react'

function formatRelativeTime(date: Date): string {
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays}d ago`
}

export default function WaDashboardPage() {
  const { dashboardStats, recentRecords, fetchDashboard, loading } = useWaStore()

  useEffect(() => {
    fetchDashboard()
  }, [fetchDashboard])

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">WA Dashboard</h1>
        <p className="text-slate-600 dark:text-slate-400 mt-1">Overview of today's field data collection</p>
      </div>

      {loading && !dashboardStats ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : dashboardStats && (
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
          <WaMetricCard title="Today's Intake" value={dashboardStats.todayIntake} href="/wa/projects" icon={<Inbox className="h-4 w-4" />} />
          <WaMetricCard title="Pending" value={dashboardStats.pendingCompletion} href="/wa/projects" icon={<Clock className="h-4 w-4" />} />
          <WaMetricCard title="Awaiting Review" value={dashboardStats.awaitingReview} href="/wa/projects" icon={<Eye className="h-4 w-4" />} />
          <WaMetricCard title="Completed" value={dashboardStats.completedToday} href="/wa/projects" icon={<CheckCircle2 className="h-4 w-4" />} />
          <WaMetricCard title="Overdue" value={dashboardStats.followUpOverdue} href="/wa/projects" icon={<AlertTriangle className="h-4 w-4" />} />
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="border-b border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-800/50 px-4 py-2.5">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Recent Activity</h2>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-700">
          {recentRecords.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <p className="text-sm text-slate-500 dark:text-slate-400">No records yet. Waiting for incoming WhatsApp messages...</p>
            </div>
          ) : (
            recentRecords.map((record) => (
              <div key={record.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200">{record.referenceNumber}</span>
                    <WaStatusBadge status={record.status} size="sm" />
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                    {record.type} · {record.senderName || record.senderPhone}
                  </p>
                </div>
                <time className="text-[11px] text-slate-500 dark:text-slate-400 whitespace-nowrap">
                  {formatRelativeTime(new Date(record.createdAt))}
                </time>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
