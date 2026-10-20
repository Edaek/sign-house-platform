import { useMemo, useState, useEffect } from 'react'
import type { WaProject } from '../../store/waStore'
import {
  buildProjectBuckets,
  bucketSiteProjects,
  isRangeBucketCode,
  isStandaloneBucketCode,
  standaloneBucketDisplayCode,
  type WaProjectBucket,
} from '../../lib/waProjects'
import { ChevronLeft, ChevronRight, Folder, Check } from 'lucide-react'

function bucketTitle(bucket: WaProjectBucket): string {
  if (isStandaloneBucketCode(bucket.code)) {
    return standaloneBucketDisplayCode(bucket.code)
  }
  return bucket.code
}

type WaProjectBucketPickerProps = {
  projects: WaProject[]
  value: string
  onChange: (projectId: string) => void
  /** Reset folder navigation when this toggles (e.g. dialog open). */
  resetKey?: string | number | boolean
}

export default function WaProjectBucketPicker({
  projects,
  value,
  onChange,
  resetKey,
}: WaProjectBucketPickerProps) {
  const [selectedBucketCode, setSelectedBucketCode] = useState<string | null>(null)

  useEffect(() => {
    setSelectedBucketCode(null)
  }, [resetKey])

  const buckets = useMemo(() => buildProjectBuckets(projects), [projects])

  const selectedBucket = useMemo(
    () => (selectedBucketCode ? buckets.find((b) => b.code === selectedBucketCode) : null),
    [buckets, selectedBucketCode],
  )

  const selectedProject = useMemo(
    () => (value ? projects.find((p) => p.id === value) : undefined),
    [projects, value],
  )

  const siteProjects = selectedBucket ? bucketSiteProjects(selectedBucket) : []

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
      {selectedProject && (
        <div className="px-3 py-2 text-xs border-b border-slate-200 dark:border-slate-700 bg-sign-50 dark:bg-sign-950/30 text-sign-800 dark:text-sign-200 flex items-center gap-1.5">
          <Check className="h-3.5 w-3.5 shrink-0" />
          <span>
            Selected: <span className="font-mono font-semibold">{selectedProject.code}</span>
          </span>
        </div>
      )}

      {selectedBucket ? (
        <>
          <button
            type="button"
            className="w-full flex items-center gap-2 px-3 py-2.5 text-sm font-medium text-slate-700 dark:text-slate-200 border-b border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/50"
            onClick={() => setSelectedBucketCode(null)}
          >
            <ChevronLeft className="h-4 w-4 shrink-0" />
            {bucketTitle(selectedBucket)}
          </button>
          <div className="max-h-56 overflow-y-auto">
            {siteProjects.length === 0 ? (
              <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400 text-center">
                No site projects in this folder
              </p>
            ) : (
              siteProjects
                .slice()
                .sort((a, b) => a.code.localeCompare(b.code))
                .map((p) => {
                  const active = value === p.id
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => onChange(p.id)}
                      className={`w-full text-left px-3 py-2.5 text-sm font-mono border-b border-slate-100 dark:border-slate-800 last:border-0 transition-colors ${
                        active
                          ? 'bg-sign-500/10 text-sign-700 dark:text-sign-300 font-semibold'
                          : 'text-slate-800 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/50'
                      }`}
                    >
                      {p.code}
                    </button>
                  )
                })
            )}
          </div>
        </>
      ) : (
        <div className="max-h-56 overflow-y-auto">
          {buckets.length === 0 ? (
            <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400 text-center">No projects</p>
          ) : (
            buckets.map((bucket) => {
              const sites = bucketSiteProjects(bucket)
              const hasChildren = sites.length > 0
              const title = bucketTitle(bucket)
              const isRange = isRangeBucketCode(bucket.code)
              return (
                <button
                  key={bucket.code}
                  type="button"
                  disabled={!hasChildren}
                  onClick={() => hasChildren && setSelectedBucketCode(bucket.code)}
                  className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm border-b border-slate-100 dark:border-slate-800 last:border-0 transition-colors ${
                    hasChildren
                      ? 'text-slate-800 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer'
                      : 'text-slate-400 dark:text-slate-500 cursor-default'
                  }`}
                >
                  <Folder
                    className={`h-4 w-4 shrink-0 ${isRange ? 'text-sign-600 dark:text-sign-400' : 'text-slate-400'}`}
                  />
                  <span className={`font-mono flex-1 text-left ${isRange ? 'font-semibold' : ''}`}>{title}</span>
                  {hasChildren ? (
                    <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />
                  ) : (
                    <span className="text-[10px] uppercase tracking-wide text-slate-400">empty</span>
                  )}
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
