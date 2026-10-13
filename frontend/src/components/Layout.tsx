import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { 
  Home, 
  FolderOpen, 
  LogOut, 
  User,
  Menu,
  X,
  Users,
  FileText,
  Book,
  MessageCircle,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import { useAuthStore } from '../store/authStore'
import { useThemeStore } from '../store/themeStore'
import ThemeToggle from './ThemeToggle'
import RoleBadge from './RoleBadge'
import clsx from 'clsx'

export default function Layout() {
  const { user, logout, isAdmin, isManager } = useAuthStore()
  const { initTheme } = useThemeStore()
  const navigate = useNavigate()
  const location = useLocation()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  
  useEffect(() => {
    initTheme()
  }, [initTheme])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }
  
  const navItems = [
    { path: '/', icon: Home, label: isManager() ? 'All Projects' : 'Dashboard' },
    { path: '/dictionary', icon: Book, label: 'Dictionary' },
    { path: '/wa', icon: MessageCircle, label: 'WA Bot' },
  ]
  
  if (isAdmin()) {
    navItems.push(
      { path: '/admin', icon: Users, label: 'User Management' },
      { path: '/audit-logs', icon: FileText, label: 'Audit Logs' }
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-bg)]">
      {/* Header */}
      <header className="relative z-50 shrink-0 h-16 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-slate-200/50 dark:border-slate-700/50 sticky top-0">
        <div className="h-full w-full px-4 sm:px-6 lg:px-8 flex items-center justify-between">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-3 group">
            <div className="w-10 h-10 bg-gradient-to-br from-sign-500 to-sign-600 rounded-xl flex items-center justify-center shadow-lg shadow-sign-500/20 group-hover:shadow-sign-500/40 transition-shadow">
              <FolderOpen className="w-5 h-5 text-white" />
            </div>
            <span className="font-display font-semibold text-xl text-slate-900 dark:text-white hidden sm:block">
              Sign House
            </span>
          </Link>
          
          {/* Desktop Nav */}
          <nav className="hidden md:flex items-center gap-1">
            {navItems.map((item) => {
              const isActive = item.path === '/'
                ? location.pathname === '/'
                : location.pathname.startsWith(item.path)
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={clsx(
                    'nav-link',
                    isActive ? 'nav-link-active' : 'nav-link-inactive'
                  )}
                >
                  <item.icon className="w-4 h-4" />
                  {item.label}
                </Link>
              )
            })}
          </nav>
          
          {/* User Menu */}
          <div className="flex items-center gap-2">
            <div className="hidden sm:flex items-center gap-3 text-slate-600 dark:text-slate-400">
              <User className="w-4 h-4" />
              <span className="text-sm">{user?.username}</span>
              {user && <RoleBadge role={user.role} size="sm" />}
            </div>
            
            <ThemeToggle />
            
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 px-3 py-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
            >
              <LogOut className="w-4 h-4" />
              <span className="hidden sm:inline text-sm">Logout</span>
            </button>
            
            {/* Mobile menu button */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="md:hidden p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
            >
              {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>
        
        {/* Mobile Nav */}
        {mobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="md:hidden absolute top-16 left-0 right-0 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700"
          >
            <nav className="p-4 space-y-2">
              {navItems.map((item) => {
                const isActive = item.path === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(item.path)
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    onClick={() => setMobileMenuOpen(false)}
                    className={clsx(
                      'nav-link px-4 py-3',
                      isActive ? 'nav-link-active' : 'nav-link-inactive'
                    )}
                  >
                    <item.icon className="w-5 h-5" />
                    {item.label}
                  </Link>
                )
              })}
            </nav>
          </motion.div>
        )}
      </header>
      
      {/* Main Content */}
      <main className="flex-1">
        <Outlet />
      </main>
      
      {/* Footer - hidden on editor pages */}
      {!location.pathname.includes('/floor/') && (
        <footer className="py-6 border-t border-slate-200 dark:border-slate-800">
          <div className="page-container py-6 text-center text-slate-500 dark:text-slate-500 text-sm">
            © {new Date().getFullYear()} Sign House. Floor Plan Analysis Tool.
          </div>
        </footer>
      )}
    </div>
  )
}

