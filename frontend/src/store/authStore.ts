import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import api from '../lib/api'

export type UserRole = 'admin' | 'manager' | 'user'

export interface User {
  id: string
  username: string
  email: string
  role: UserRole
  created_at: string
  is_active: boolean
}

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  
  login: (username: string, password: string) => Promise<void>
  register: (username: string, email: string, password: string) => Promise<void>
  logout: () => void
  fetchUser: () => Promise<void>
  clearError: () => void
  
  // Permission checking methods
  isAdmin: () => boolean
  isManager: () => boolean
  canAccessAllProjects: () => boolean
  canManageUsers: () => boolean
  canViewAuditLogs: () => boolean
  canAccessProject: (projectOwnerId: string) => boolean
  canModifyProject: (projectOwnerId: string) => boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
      
      login: async (username: string, password: string) => {
        set({ isLoading: true, error: null })
        try {
          const response = await api.post('/auth/login', { username, password })
          const { user, access_token } = response.data
          
          set({
            user,
            token: access_token,
            isAuthenticated: true,
            isLoading: false
          })
          
          // Set token for future requests
          api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
        } catch (error: unknown) {
          const ax = error as {
            response?: { status?: number; data?: { error?: string } }
            code?: string
            message?: string
          }
          let message = ax.response?.data?.error
          if (!message) {
            if (ax.response?.status === 502) {
              message = '后端未响应 (502)。请在终端执行: cd backend && .venv/bin/python run.py'
            } else if (!ax.response || ax.code === 'ECONNABORTED' || ax.code === 'ERR_NETWORK') {
              message = '无法连接后端 (5002)，请确认 backend 已启动'
            } else {
              message = 'Login failed'
            }
          }
          set({ isLoading: false, error: message })
          throw error
        }
      },
      
      register: async (username: string, email: string, password: string) => {
        set({ isLoading: true, error: null })
        try {
          const response = await api.post('/auth/register', { username, email, password })
          const { user, access_token } = response.data
          
          set({
            user,
            token: access_token,
            isAuthenticated: true,
            isLoading: false
          })
          
          api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
        } catch (error: any) {
          set({
            isLoading: false,
            error: error.response?.data?.error || 'Registration failed'
          })
          throw error
        }
      },
      
      logout: () => {
        set({
          user: null,
          token: null,
          isAuthenticated: false,
          error: null
        })
        delete api.defaults.headers.common['Authorization']
      },
      
      fetchUser: async () => {
        const { token } = get()
        if (!token) return
        
        try {
          api.defaults.headers.common['Authorization'] = `Bearer ${token}`
          const response = await api.get('/auth/me')
          set({ user: response.data.user })
        } catch {
          // Token expired or invalid
          get().logout()
        }
      },
      
      clearError: () => set({ error: null }),
      
      // Permission checking methods
      isAdmin: () => {
        const { user } = get()
        return user?.role === 'admin'
      },
      
      isManager: () => {
        const { user } = get()
        return user?.role === 'admin' || user?.role === 'manager'
      },
      
      canAccessAllProjects: () => {
        const { user } = get()
        return user?.role === 'admin' || user?.role === 'manager'
      },
      
      canManageUsers: () => {
        const { user } = get()
        return user?.role === 'admin'
      },
      
      canViewAuditLogs: () => {
        const { user } = get()
        return user?.role === 'admin'
      },
      
      canAccessProject: (projectOwnerId: string) => {
        const { user } = get()
        if (!user) return false
        // Admins and managers can access all projects
        if (user.role === 'admin' || user.role === 'manager') return true
        // Regular users can only access their own projects
        return user.id === projectOwnerId
      },
      
      canModifyProject: (projectOwnerId: string) => {
        const { user } = get()
        if (!user) return false
        // Admins can modify any project
        if (user.role === 'admin') return true
        // Project owners can modify their own projects
        return user.id === projectOwnerId
      }
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ token: state.token, user: state.user, isAuthenticated: state.isAuthenticated })
    }
  )
)

// Initialize auth state on app load
const initAuth = () => {
  const { token, fetchUser } = useAuthStore.getState()
  if (token) {
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`
    fetchUser()
  }
}

initAuth()

