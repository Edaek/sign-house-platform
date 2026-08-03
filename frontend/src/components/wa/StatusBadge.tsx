import clsx from 'clsx'

const slateBadge = 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600'
const signBadge = 'bg-sign-500/15 text-sign-700 border-sign-500/25 dark:bg-sign-500/20 dark:text-sign-400 dark:border-sign-500/30'
const mutedBadge = 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-800/50 dark:text-slate-500 dark:border-slate-700'

const statusConfig: Record<string, { label: string; className: string }> = {
  incomplete: { label: 'Incomplete', className: slateBadge },
  followup: { label: 'Follow-up', className: signBadge },
  awaiting_review: { label: 'Awaiting Review', className: signBadge },
  completed: { label: 'Completed', className: signBadge },
  voided: { label: 'Voided', className: mutedBadge },
  active: { label: 'Active', className: signBadge },
  in_progress: { label: 'In Progress', className: signBadge },
  planning: { label: 'Planning', className: slateBadge },
  hold: { label: 'On Hold', className: slateBadge },
  archived: { label: 'Archived', className: mutedBadge },
}

interface StatusBadgeProps {
  status: string
  size?: 'sm' | 'default'
}

export default function WaStatusBadge({ status, size = 'default' }: StatusBadgeProps) {
  const config = statusConfig[status] || {
    label: status,
    className: slateBadge,
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
