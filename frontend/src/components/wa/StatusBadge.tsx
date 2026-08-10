import clsx from 'clsx'
import { formatStatusLabel, getStatusStyle } from '../../lib/theme'

interface WaStatusBadgeProps {
  status: string
  size?: 'sm' | 'default'
}

export default function WaStatusBadge({ status, size = 'default' }: WaStatusBadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full border font-medium',
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-0.5 text-xs',
        getStatusStyle(status)
      )}
    >
      {formatStatusLabel(status)}
    </span>
  )
}
