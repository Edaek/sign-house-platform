import clsx from 'clsx'
import { formatStatusLabel, getStatusStyle } from '../lib/theme'

interface StatusBadgeProps {
  status: string
  label?: string
  size?: 'sm' | 'default'
}

export default function StatusBadge({ status, label, size = 'default' }: StatusBadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full border font-medium',
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-0.5 text-xs',
        getStatusStyle(status)
      )}
    >
      {label ?? formatStatusLabel(status)}
    </span>
  )
}
