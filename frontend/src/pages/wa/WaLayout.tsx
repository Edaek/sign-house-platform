import { Outlet, Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'
import clsx from 'clsx'
import PageContainer from '../../components/PageContainer'
import {
  LayoutDashboard,
  FolderOpen,
  Image,
  Search,
  Tag,
  BookText,
  Settings2,
  Radio,
  Users,
} from 'lucide-react'

interface NavItem {
  path: string
  icon: React.ComponentType<{ className?: string }>
  label: string
  exact?: boolean
}

const mainNav: NavItem[] = [
  { path: '/wa', icon: LayoutDashboard, label: 'Dashboard', exact: true },
  { path: '/wa/projects', icon: FolderOpen, label: 'Projects' },
  { path: '/wa/image-pool', icon: Image, label: 'Image Pool' },
  { path: '/wa/search', icon: Search, label: 'Search' },
]

const adminNav: NavItem[] = [
  { path: '/wa/admin/keywords', icon: Tag, label: 'Dictionary' },
  { path: '/wa/admin/templates', icon: BookText, label: 'Templates' },
  { path: '/wa/admin/projects', icon: Settings2, label: 'Manage Projects' },
  { path: '/wa/admin/system', icon: Radio, label: 'System' },
  { path: '/wa/admin/users', icon: Users, label: 'Users' },
]

export default function WaLayout() {
  const location = useLocation()
  const { isAdmin } = useAuthStore()

  const allNav = isAdmin() ? [...mainNav, ...adminNav] : mainNav

  const isActive = (path: string, exact?: boolean) => {
    if (exact) return location.pathname === path
    return location.pathname.startsWith(path)
  }

  return (
    <PageContainer className="py-6">
      <div className="flex items-center gap-1 mb-6 overflow-x-auto pb-1 scrollbar-hide">
        {allNav.map((item) => {
          const active = isActive(item.path, item.exact)
          return (
            <Link
              key={item.path}
              to={item.path}
              className={clsx(
                'nav-link',
                active ? 'nav-link-active' : 'nav-link-inactive'
              )}
            >
              <item.icon className="w-4 h-4 shrink-0" />
              {item.label}
            </Link>
          )
        })}
      </div>

      <Outlet />
    </PageContainer>
  )
}
