import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'light' | 'dark' | 'system'
type ResolvedTheme = 'light' | 'dark'

interface ThemeStore {
  theme: Theme
  resolvedTheme: ResolvedTheme
  setTheme: (theme: Theme) => void
  initTheme: () => void
}

const getSystemTheme = (): ResolvedTheme => {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const applyTheme = (resolvedTheme: ResolvedTheme) => {
  const root = document.documentElement
  if (resolvedTheme === 'dark') {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set, get) => ({
      theme: 'system',
      resolvedTheme: 'dark',
      
      setTheme: (theme: Theme) => {
        const resolvedTheme = theme === 'system' ? getSystemTheme() : theme
        applyTheme(resolvedTheme)
        set({ theme, resolvedTheme })
      },
      
      initTheme: () => {
        const { theme } = get()
        const resolvedTheme = theme === 'system' ? getSystemTheme() : theme
        applyTheme(resolvedTheme)
        set({ resolvedTheme })
        
        // Listen for system theme changes
        if (typeof window !== 'undefined') {
          const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
          const handleChange = (e: MediaQueryListEvent) => {
            const { theme } = get()
            if (theme === 'system') {
              const newResolvedTheme = e.matches ? 'dark' : 'light'
              applyTheme(newResolvedTheme)
              set({ resolvedTheme: newResolvedTheme })
            }
          }
          
          // Modern browsers
          if (mediaQuery.addEventListener) {
            mediaQuery.addEventListener('change', handleChange)
          } else {
            // Fallback for older browsers
            mediaQuery.addListener(handleChange)
          }
        }
      },
    }),
    {
      name: 'sign-house-theme',
      partialize: (state) => ({ theme: state.theme }),
    }
  )
)

