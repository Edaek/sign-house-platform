import { useEffect, useState, useCallback } from 'react'
import { useWaStore } from '../../store/waStore'
import clsx from 'clsx'
import {
  Radio,
  Database,
  Brain,
  Wifi,
  WifiOff,
  Phone,
  Coins,
  RefreshCw,
  CircleDot,
} from 'lucide-react'

function StatusDot({ status }: { status: 'ok' | 'error' | 'checking' | boolean }) {
  const isOk = status === 'ok' || status === true
  const isChecking = status === 'checking'
  return (
    <span className={clsx(
      'inline-block h-2 w-2 rounded-full',
      isOk && 'bg-sign-500',
      (status === 'error' || status === false) && 'bg-slate-400 dark:bg-slate-500',
      isChecking && 'bg-slate-300 dark:bg-slate-600 animate-pulse'
    )} />
  )
}

export default function WaSystemPage() {
  const { systemStatus, infraStatus, fetchSystemStatus, fetchInfraStatus } = useWaStore()
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const loadAll = useCallback(async () => {
    await Promise.all([fetchSystemStatus(), fetchInfraStatus()])
    setLoading(false)
  }, [fetchSystemStatus, fetchInfraStatus])

  useEffect(() => {
    loadAll()
    const interval = setInterval(fetchSystemStatus, 10000)
    return () => clearInterval(interval)
  }, [loadAll, fetchSystemStatus])

  async function handleRefresh() {
    setRefreshing(true)
    await Promise.all([fetchSystemStatus(), fetchInfraStatus()])
    setRefreshing(false)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">WhatsApp & System</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Live status of services and connections</p>
        </div>
        <button onClick={handleRefresh} disabled={refreshing} className="btn btn-secondary text-sm px-3 py-1.5 flex items-center gap-1.5">
          <RefreshCw className={clsx('h-3.5 w-3.5', refreshing && 'animate-spin')} />Refresh
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* WhatsApp Connection */}
        <div className="rounded-lg border border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-4 py-2.5">
            <Radio className="h-4 w-4 text-slate-400" />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">WhatsApp (Wakka)</span>
          </div>
          <div className="p-4">
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />Connecting...
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-500 dark:text-slate-400">Session</span>
                  <div className="flex items-center gap-2">
                    {systemStatus?.connected ? <Wifi className="h-4 w-4 text-sign-500" /> : <WifiOff className="h-4 w-4 text-slate-400" />}
                    <span className={clsx(
                      'text-sm font-medium',
                      systemStatus?.connected ? 'text-sign-600 dark:text-sign-400' : 'text-slate-500 dark:text-slate-400'
                    )}>
                      {systemStatus?.connected ? 'Connected' : systemStatus?.status || 'Disconnected'}
                    </span>
                  </div>
                </div>
                {systemStatus?.phoneNumber && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-500 dark:text-slate-400">Phone</span>
                    <span className="flex items-center gap-1.5 text-sm font-mono text-slate-800 dark:text-slate-200">
                      <Phone className="h-3.5 w-3.5 text-slate-400" />{systemStatus.phoneNumber}
                    </span>
                  </div>
                )}
                {systemStatus?.plan && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-500 dark:text-slate-400">Plan</span>
                    <span className="inline-flex items-center rounded-md bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs font-medium capitalize text-slate-600 dark:text-slate-400">
                      {systemStatus.plan}
                    </span>
                  </div>
                )}
                {systemStatus?.tokenBalance !== undefined && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-500 dark:text-slate-400">Tokens</span>
                    <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-200">
                      <Coins className="h-3.5 w-3.5 text-slate-400" />{systemStatus.tokenBalance.toLocaleString()}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Infrastructure */}
        <div className="rounded-lg border border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-4 py-2.5">
            <CircleDot className="h-4 w-4 text-slate-400" />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Infrastructure</span>
          </div>
          <div className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400"><Database className="h-3.5 w-3.5" />MongoDB</span>
              <div className="flex items-center gap-2">
                <StatusDot status={infraStatus.mongo} />
                <span className="text-sm capitalize text-slate-700 dark:text-slate-300">{infraStatus.mongo}</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400"><Brain className="h-3.5 w-3.5" />Ollama (AI)</span>
              <div className="flex items-center gap-2">
                <StatusDot status={infraStatus.ollama} />
                <span className="text-sm capitalize text-slate-700 dark:text-slate-300">{infraStatus.ollama}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* API Token Costs */}
      <div className="rounded-lg border border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-4 py-2.5">
          <Coins className="h-4 w-4 text-slate-400" />
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Wakka API Token Costs</span>
        </div>
        <div className="grid grid-cols-3 divide-x divide-slate-200 dark:divide-slate-700 text-center">
          <div className="p-4">
            <p className="text-lg font-bold text-slate-800 dark:text-slate-200">1</p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Text Message</p>
          </div>
          <div className="p-4">
            <p className="text-lg font-bold text-slate-800 dark:text-slate-200">2</p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Media Message</p>
          </div>
          <div className="p-4">
            <p className="text-lg font-bold text-sign-600 dark:text-sign-400">Free</p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Read Operations</p>
          </div>
        </div>
      </div>
    </div>
  )
}
