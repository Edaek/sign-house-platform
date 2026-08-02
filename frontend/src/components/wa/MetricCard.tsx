import { Link } from 'react-router-dom'
import clsx from 'clsx'

interface MetricCardProps {
  title: string
  value: number
  href: string
  icon?: React.ReactNode
  color?: 'default' | 'orange' | 'amber' | 'purple' | 'emerald' | 'red' | 'blue'
}

const colorMap: Record<string, string> = {
  default: 'border-l-orange-400',
  orange: 'border-l-orange-500',
  amber: 'border-l-amber-500',
  purple: 'border-l-purple-500',
  emerald: 'border-l-emerald-500',
  red: 'border-l-red-500',
  blue: 'border-l-blue-500',
}

const valueColorMap: Record<string, string> = {
  default: 'text-orange-600 dark:text-orange-400',
  orange: 'text-orange-600 dark:text-orange-400',
  amber: 'text-amber-600 dark:text-amber-400',
  purple: 'text-purple-600 dark:text-purple-400',
  emerald: 'text-emerald-600 dark:text-emerald-400',
  red: 'text-red-600 dark:text-red-400',
  blue: 'text-blue-600 dark:text-blue-400',
}

export default function WaMetricCard({ title, value, href, icon, color = 'default' }: MetricCardProps) {
  return (
    <Link to={href}>
      <div
        className={clsx(
          'rounded-lg border border-l-4 bg-white dark:bg-slate-800/50 p-4 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors cursor-pointer',
          colorMap[color]
        )}
      >
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide">
            {title}
          </span>
          {icon && <span className="text-slate-400 dark:text-slate-500">{icon}</span>}
        </div>
        <p className={clsx('text-2xl font-bold', value > 0 ? valueColorMap[color] : 'text-slate-400 dark:text-slate-500')}>
          {value}
        </p>
      </div>
    </Link>
  )
}
