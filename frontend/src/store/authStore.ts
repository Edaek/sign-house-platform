import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import api from '../lib/api'

interface User {
  id: string
  username: string
  email: string
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
        } catch (error: any) {
          set({
            isLoading: false,
            error: error.response?.data?.error || 'Login failed'
          })
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
      
      clearError: () => set({ error: null })
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

