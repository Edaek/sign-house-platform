import { Link } from 'react-router-dom'
import clsx from 'clsx'

interface MetricCardProps {
  title: string
  value: number
  href: string
  icon?: React.ReactNode
}

export default function WaMetricCard({ title, value, href, icon }: MetricCardProps) {
  return (
    <Link to={href}>
      <div className="card p-4 hover:border-sign-500/30 transition-colors cursor-pointer">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide">
            {title}
          </span>
          {icon && <span className="text-slate-400 dark:text-slate-500">{icon}</span>}
        </div>
        <p className={clsx(
          'text-2xl font-bold',
          value > 0 ? 'text-sign-600 dark:text-sign-400' : 'text-slate-400 dark:text-slate-500'
        )}>
          {value}
        </p>
      </div>
    </Link>
  )
}
