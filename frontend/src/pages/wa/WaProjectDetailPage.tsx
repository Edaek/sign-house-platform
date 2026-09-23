import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useWaStore } from '../../store/waStore'
import WaStatusBadge from '../../components/wa/StatusBadge'
import WaRecordTable from '../../components/wa/RecordTable'
import { MapPin, Layers, HardDrive, ChevronLeft } from 'lucide-react'
import api from '../../lib/api'

interface ProjectDetail {
  id?: string
  code: string
  name: string
  location?: string
  stage: string
  status: string
  totalRecords?: number
  nasFileCount?: number
  nasPendingImport?: number
}

export default function WaProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { records, fetchProjectRecords, nasStatus, fetchNasStatus } = useWaStore()
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [projectLoading, setProjectLoading] = useState(true)
  const [recordsLoading, setRecordsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setProject(null)
    setProjectLoading(true)
    setRecordsLoading(true)
    setLoadError(null)

    api.get(`/wa/projects/${id}`)
      .then(({ data }) => {
        if (!cancelled) setProject(data)
      })
      .catch(() => {
        if (!cancelled) setLoadError('Failed to load project')
      })
      .finally(() => {
        if (!cancelled) setProjectLoading(false)
      })

    fetchProjectRecords(id).finally(() => {
      if (!cancelled) setRecordsLoading(false)
    })

    fetchNasStatus()

    return () => {
      cancelled = true
    }
  }, [id, fetchProjectRecords, fetchNasStatus])

  useEffect(() => {
    if (!id || !nasStatus?.connected) return
    const sec = nasStatus.autoSyncIntervalSec ?? 60
    const ms = Math.max(30, sec) * 1000
    const timer = window.setInterval(() => {
      api.get(`/wa/projects/${id}`).then(({ data }) => setProject(data)).catch(() => {})
      fetchProjectRecords(id)
    }, ms)
    return () => window.clearInterval(timer)
  }, [id, nasStatus?.connected, nasStatus?.autoSyncIntervalSec, fetchProjectRecords])

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }

  if (loadError || !project) {
    return <div className="text-center py-20 text-slate-500">{loadError || 'Project not found'}</div>
  }

  return (
    <div className="space-y-6">
      <Link
        to="/wa/projects"
        className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
      >
        <ChevronLeft className="h-4 w-4" />
        Back to Projects
      </Link>

      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">
              <span className="font-mono text-sign-600 dark:text-sign-400">{project.code}</span>
              <span className="mx-2 text-slate-400">—</span>
              {project.name}
            </h1>
            <WaStatusBadge status={project.status} />
          </div>
          <div className="flex items-center gap-3 mt-1 text-sm text-slate-500 dark:text-slate-400">
            {project.location && (
              <span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{project.location}</span>
            )}
            <span className="flex items-center gap-1"><Layers className="h-3.5 w-3.5" />{project.stage}</span>
            <span>
              {project.totalRecords ?? records.length} record
              {(project.totalRecords ?? records.length) !== 1 ? 's' : ''}
            </span>
            {(project.nasFileCount ?? 0) > 0 && (
              <span className="flex items-center gap-1">
                <HardDrive className="h-3.5 w-3.5" />
                {project.nasFileCount} on NAS
                {(project.nasPendingImport ?? 0) > 0 && (
                  <span className="text-amber-600 dark:text-amber-400">
                    ({project.nasPendingImport} pending import)
                  </span>
                )}
              </span>
            )}
          </div>
        </div>
      </div>

      {recordsLoading ? (
        <div className="flex items-center justify-center py-16 rounded-lg border border-slate-200 dark:border-slate-700">
          <div className="w-7 h-7 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : (
        <WaRecordTable records={records} />
      )}
    </div>
  )
}
