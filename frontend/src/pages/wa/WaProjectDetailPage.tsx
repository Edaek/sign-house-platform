import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useWaStore } from '../../store/waStore'
import WaStatusBadge from '../../components/wa/StatusBadge'
import WaRecordTable from '../../components/wa/RecordTable'
import { MapPin, Layers } from 'lucide-react'
import api from '../../lib/api'

interface ProjectDetail {
  _id: string
  code: string
  name: string
  location?: string
  stage: string
  status: string
}

export default function WaProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { records, fetchProjectRecords, loading } = useWaStore()
  const [project, setProject] = useState<ProjectDetail | null>(null)

  useEffect(() => {
    if (!id) return
    api.get(`/wa/projects/${id}`).then(({ data }) => setProject(data))
    fetchProjectRecords(id)
  }, [id, fetchProjectRecords])

  if (!project && loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }

  if (!project) {
    return <div className="text-center py-20 text-slate-500">Project not found</div>
  }

  return (
    <div className="space-y-6">
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
            <span>{records.length} record{records.length !== 1 ? 's' : ''}</span>
          </div>
        </div>
      </div>

      <WaRecordTable records={records} />
    </div>
  )
}
