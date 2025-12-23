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

// Template data functions (for editable preview)
export interface TemplateCell {
  col: number
  letter: string
  value: string | number
}

export interface TemplateRow {
  row: number
  cells: TemplateCell[]
}

export interface TemplateColumn {
  name: string
  column: number
  letter: string
}

export interface TemplateData {
  columns: TemplateColumn[]
  rows: TemplateRow[]
  total_rows: number
  total_columns: number
  ocr_cells: { row: number; col: number }[]
}

export interface TemplateDataResponse {
  template: {
    id: string
    filename: string
    filepath: string
    columns: TemplateColumn[]
    floor_mapping?: Record<string, string>
  }
  data: TemplateData
}

export const getTemplateData = async (projectId: string): Promise<TemplateDataResponse> => {
  const response = await api.get(`/export/template-data/${projectId}`)
  return response.data
}

export interface CellUpdate {
  row: number
  col: number
  value: string | number
}

export const updateTemplateCell = async (projectId: string, row: number, col: number, value: string | number) => {
  const response = await api.put(`/export/template-data/${projectId}`, {
    row,
    col,
    value,
  })
  return response.data
}

export const updateTemplateCells = async (projectId: string, updates: CellUpdate[]) => {
  const response = await api.put(`/export/template-data/${projectId}`, {
    updates,
  })
  return response.data
}

// Sign Table API functions (auto-generated from OCR data)
export interface SignRow {
  row_number: number
  sign_no: string
  sign: string
  english: string
  chinese: string
  floor_counts: Record<string, number>
}

export interface SignTable {
  id: string
  project_id: string
  rows: SignRow[]
  floorplan_columns: string[]
  created_at: string
  updated_at: string
}

export interface SignTableResponse {
  sign_table: SignTable
  project: {
    id: string
    name: string
    status: string
  }
}

// Sign table cell update response
export interface SignTableCellUpdateResponse {
  message: string
  row_number: number
  field: string
  value: string
  sign_auto_filled?: string
  chinese_auto_filled?: string
  dictionary_updated?: boolean
}

export const getSignTableData = async (projectId: string): Promise<SignTableResponse> => {
  const response = await api.get(`/export/sign-table/${projectId}`)
  return response.data
}

export const updateSignTableCell = async (
  projectId: string,
  rowNumber: number,
  field: 'sign' | 'english' | 'chinese',
  value: string
): Promise<SignTableCellUpdateResponse> => {
  const response = await api.put(`/export/sign-table/${projectId}`, {
    row_number: rowNumber,
    field,
    value,
  })
  return response.data
}

// Dictionary search for autocomplete
export interface DictionarySearchResult {
  english: string
  sign: string
  chinese: string[]
  match_type: 'prefix' | 'contains'
}

export interface DictionarySearchResponse {
  results: DictionarySearchResult[]
  query: string
  count: number
}

export const searchDictionary = async (query: string, limit = 10): Promise<DictionarySearchResponse> => {
  const response = await api.get(`/dictionary/search?q=${encodeURIComponent(query)}&limit=${limit}`)
  return response.data
}

// Add translation to dictionary
export interface AddToDictionaryResponse {
  action: 'created' | 'added' | 'exists'
  message: string
  entry: {
    id: string
    english: string
    sign: string
    chinese: string[]
  }
}

export const addToDictionary = async (english: string, chinese: string): Promise<AddToDictionaryResponse> => {
  const response = await api.post('/dictionary/add-translation', {
    english,
    chinese,
  })
  return response.data
}

export default api

