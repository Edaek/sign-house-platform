import type { ConfidenceLevel } from '../../store/waStore'

const confidenceConfig: Record<ConfidenceLevel, { label: string; className: string }> = {
  green: { label: 'High', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
  yellow: { label: 'Medium', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
  red: { label: 'Low', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
  gray: { label: 'N/A', className: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300' },
}

interface ConfidenceBadgeProps {
  confidence: ConfidenceLevel
}

export default function WaConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const config = confidenceConfig[confidence]
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${config.className}`}>
      {config.label}
    </span>
  )
}
