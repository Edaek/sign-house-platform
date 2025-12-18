import axios from 'axios'

// Use environment variable for API URL, fallback to relative path for development
// In development: VITE_API_URL should be empty/undefined, uses '/api' with Vite proxy
// In production: VITE_API_URL should be 'https://your-backend.coolify.domain' (without /api)
const getBaseURL = () => {
  const apiUrl = import.meta.env.VITE_API_URL
  if (apiUrl && apiUrl.trim()) {
    // Production: append /api to backend URL
    return `${apiUrl}/api`
  }
  // Development: use relative path with Vite proxy
  return '/api'
}

const api = axios.create({
  baseURL: getBaseURL(),
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
})

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear auth state and redirect to login
      localStorage.removeItem('auth-storage')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Template mapping functions
export const saveTemplateMapping = async (projectId: string, floorMapping: Record<string, string>) => {
  const response = await api.put(`/projects/${projectId}/template/mapping`, {
    floor_mapping: floorMapping,
  })
  return response.data
}

export const getTemplateMapping = async (projectId: string) => {
  const response = await api.get(`/projects/${projectId}/template/mapping`)
  return response.data
}

export default api

