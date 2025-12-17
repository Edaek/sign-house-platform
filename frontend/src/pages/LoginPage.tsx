import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { LogIn, Eye, EyeOff, FolderOpen } from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import toast from 'react-hot-toast'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const { login, isLoading, error, clearError } = useAuthStore()
  const navigate = useNavigate()
  
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    
    try {
      await login(username, password)
      toast.success('Welcome back!')
      navigate('/')
    } catch {
      toast.error(error || 'Login failed')
    }
  }
  
  return (
    <div className="min-h-screen flex">
      {/* Left Panel - Branding */}
      <div className="hidden lg:flex lg:w-1/2 blueprint-bg relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-white/60 to-blueprint-100/80 dark:from-blueprint-950/90 dark:to-blueprint-900/80" />
        
        <div className="relative z-10 flex flex-col justify-center px-16">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <div className="flex items-center gap-4 mb-8">
              <div className="w-16 h-16 bg-gradient-to-br from-sign-500 to-sign-600 rounded-2xl flex items-center justify-center shadow-2xl shadow-sign-500/30">
                <FolderOpen className="w-8 h-8 text-white" />
              </div>
              <div>
                <h1 className="text-4xl font-display font-bold text-slate-900 dark:text-white">Sign House</h1>
                <p className="text-blueprint-700 dark:text-blueprint-300 font-medium">Floor Plan Analysis</p>
              </div>
            </div>
            
            <p className="text-xl text-slate-700 dark:text-blueprint-200 leading-relaxed max-w-md">
              Extract room labels, areas, and data from floor plans using 
              computer vision and OCR technology.
            </p>
            
            <div className="mt-12 space-y-4">
              <Feature text="Automatic shape detection (circles & rectangles)" />
              <Feature text="Intelligent OCR text extraction" />
              <Feature text="Export to Excel with custom templates" />
              <Feature text="Multi-floor PDF support" />
            </div>
          </motion.div>
        </div>
        
        {/* Decorative elements */}
        <div className="absolute bottom-0 right-0 w-96 h-96 bg-blueprint-500/10 rounded-full blur-3xl" />
        <div className="absolute top-20 right-20 w-64 h-64 bg-sign-500/10 rounded-full blur-3xl" />
      </div>
      
      {/* Right Panel - Login Form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-slate-50 dark:bg-slate-900">
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4 }}
          className="w-full max-w-md"
        >
          {/* Mobile Logo */}
          <div className="lg:hidden flex items-center gap-3 mb-8 justify-center">
            <div className="w-12 h-12 bg-gradient-to-br from-sign-500 to-sign-600 rounded-xl flex items-center justify-center">
              <FolderOpen className="w-6 h-6 text-white" />
            </div>
            <span className="text-2xl font-display font-bold text-slate-900 dark:text-white">Sign House</span>
          </div>
          
          <div className="card p-8">
            <h2 className="text-2xl font-display font-semibold text-slate-900 dark:text-white mb-2">
              Welcome back
            </h2>
            <p className="text-slate-600 dark:text-slate-400 mb-8">
              Sign in to continue to your projects
            </p>
            
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="username" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                  Username or Email
                </label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input"
                  placeholder="Enter your username"
                  required
                  autoComplete="username"
                />
              </div>
              
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="input pr-12"
                    placeholder="Enter your password"
                    required
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
                  >
                    {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                  </button>
                </div>
              </div>
              
              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm"
                >
                  {error}
                </motion.div>
              )}
              
              <button
                type="submit"
                disabled={isLoading}
                className="btn btn-primary w-full py-3 flex items-center justify-center gap-2"
              >
                {isLoading ? (
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <>
                    <LogIn className="w-5 h-5" />
                    Sign In
                  </>
                )}
              </button>
            </form>
            
            <p className="mt-6 text-center text-slate-600 dark:text-slate-400">
              Don't have an account?{' '}
              <Link to="/register" className="text-sign-500 hover:text-sign-400 dark:text-sign-400 dark:hover:text-sign-300 font-medium">
                Create one
              </Link>
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  )
}

function Feature({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-2 h-2 bg-sign-500 rounded-full" />
      <span className="text-slate-700 dark:text-blueprint-200">{text}</span>
    </div>
  )
}

