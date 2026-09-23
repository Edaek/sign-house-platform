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
  { path: '/wa/image-pool', icon: Image, label: 'Media Pool' },
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
    <>
      <div className="sticky top-16 z-40 border-b border-slate-200/80 dark:border-slate-700/80 bg-[var(--color-bg)]/95 backdrop-blur-md supports-[backdrop-filter]:bg-[var(--color-bg)]/80">
        <PageContainer className="!py-3">
          <div className="flex items-center gap-1 overflow-x-auto pb-0.5 scrollbar-hide -mb-0.5">
            {allNav.map((item) => {
              const active = isActive(item.path, item.exact)
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={clsx(
                    'nav-link shrink-0',
                    active ? 'nav-link-active' : 'nav-link-inactive'
                  )}
                >
                  <item.icon className="w-4 h-4 shrink-0" />
                  {item.label}
                </Link>
              )
            })}
          </div>
        </PageContainer>
      </div>

      <PageContainer className="pt-6 pb-8">
        <Outlet />
      </PageContainer>
    </>
  )
}
