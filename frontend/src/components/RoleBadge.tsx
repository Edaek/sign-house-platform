import { UserRole } from '../store/authStore'
import { getRoleDisplayName, getRoleColorClass } from '../lib/permissions'

interface RoleBadgeProps {
  role: UserRole
  size?: 'sm' | 'md' | 'lg'
}

export default function RoleBadge({ role, size = 'md' }: RoleBadgeProps) {
  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5',
    md: 'text-sm px-2.5 py-0.5',
    lg: 'text-base px-3 py-1',
  }

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ${getRoleColorClass(role)} ${sizeClasses[size]}`}
    >
      {getRoleDisplayName(role)}
    </span>
  )
}

