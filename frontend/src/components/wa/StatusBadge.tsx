import clsx from 'clsx'

const statusConfig: Record<string, { label: string; className: string }> = {
  incomplete: {
    label: 'Incomplete',
    className: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
  },
  followup: {
    label: 'Follow-up',
    className: 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800',
  },
  awaiting_review: {
    label: 'Awaiting Review',
    className: 'bg-purple-100 text-purple-800 border-purple-200 dark:bg-purple-950 dark:text-purple-300 dark:border-purple-800',
  },
  completed: {
    label: 'Completed',
    className: 'bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-800',
  },
  voided: {
    label: 'Voided',
    className: 'bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-800',
  },
  active: {
    label: 'Active',
    className: 'bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-950 dark:text-orange-300 dark:border-orange-800',
  },
  in_progress: {
    label: 'In Progress',
    className: 'bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-950 dark:text-orange-300 dark:border-orange-800',
  },
  planning: {
    label: 'Planning',
    className: 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800',
  },
  hold: {
    label: 'On Hold',
    className: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
  },
  archived: {
    label: 'Archived',
    className: 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700',
  },
}

interface StatusBadgeProps {
  status: string
  size?: 'sm' | 'default'
}

export default function WaStatusBadge({ status, size = 'default' }: StatusBadgeProps) {
  const config = statusConfig[status] || {
    label: status,
    className: 'bg-gray-100 text-gray-600 border-gray-200',
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full border font-medium',
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-0.5 text-xs',
        config.className
      )}
    >
      {config.label}
    </span>
  )
}
