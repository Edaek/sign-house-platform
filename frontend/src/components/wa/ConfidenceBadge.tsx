import clsx from 'clsx'
import type { ConfidenceLevel } from '../../store/waStore'

const confidenceConfig: Record<ConfidenceLevel, { label: string; className: string }> = {
  green: {
    label: 'High',
    className: 'bg-sign-500/15 text-sign-700 dark:bg-sign-500/20 dark:text-sign-400',
  },
  yellow: {
    label: 'Medium',
    className: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  },
  red: {
    label: 'Low',
    className: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
  },
  gray: {
    label: 'N/A',
    className: 'bg-slate-50 text-slate-500 dark:bg-slate-800/50 dark:text-slate-500',
  },
}

interface ConfidenceBadgeProps {
  confidence: ConfidenceLevel
}

export default function WaConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const config = confidenceConfig[confidence]
  return (
    <span className={clsx('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', config.className)}>
      {config.label}
    </span>
  )
}
