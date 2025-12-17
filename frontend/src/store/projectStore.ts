import { create } from 'zustand'
import api from '../lib/api'

interface Template {
  id: string
  filename: string
  columns: { name: string; column: number; letter: string }[]
  created_at: string
}

interface ExtractedData {
  id: string
  shape_index: number
  shape_type: string
  x: number
  y: number
  width: number
  height: number
  extracted_text: string | null
  confidence: number | null
  quantity: number  // Quantity multiplier (defaults to 1)
  is_manual: boolean
  manual_text: string | null
  display_text: string | null
}

interface FloorPlan {
  id: string
  floor_number: number
  floor_name: string
  pdf_filename: string
  image_filepath: string | null
  shape_type: string | null
  status: string
  data_count: number
  extracted_data?: ExtractedData[]
}

interface Project {
  id: string
  name: string
  description: string | null
  status: string
  created_at: string
  updated_at: string
  floorplan_count: number
  template?: Template | null
  floorplans?: FloorPlan[]
}

interface ProjectState {
  projects: Project[]
  currentProject: Project | null
  currentFloorplan: FloorPlan | null
  isLoading: boolean
  error: string | null
  
  fetchProjects: () => Promise<void>
  fetchProject: (id: string) => Promise<void>
  createProject: (name: string, description?: string) => Promise<Project>
  updateProject: (id: string, data: Partial<Project>) => Promise<void>
  deleteProject: (id: string) => Promise<void>
  
  uploadTemplate: (projectId: string, file: File) => Promise<void>
  uploadFloorplan: (projectId: string, file: File) => Promise<void>
  
  fetchFloorplan: (projectId: string, floorplanId: string) => Promise<void>
  updateFloorplan: (projectId: string, floorplanId: string, data: Partial<FloorPlan>) => Promise<void>
  deleteFloorplan: (projectId: string, floorplanId: string) => Promise<void>
  
  detectShapes: (floorplanId: string, shapeType?: string) => Promise<ExtractedData[]>
  runOCR: (floorplanId: string) => Promise<ExtractedData[]>
  ocrRegion: (floorplanId: string, region: { x: number; y: number; width: number; height: number }) => Promise<ExtractedData>
  updateExtractedData: (dataId: string, manualText?: string, quantity?: number) => Promise<void>
  deleteExtractedData: (dataId: string) => Promise<void>
  
  clearError: () => void
}

export const useProjectStore = create<ProjectState>()((set, get) => ({
  projects: [],
  currentProject: null,
  currentFloorplan: null,
  isLoading: false,
  error: null,
  
  fetchProjects: async () => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.get('/projects')
      set({ projects: response.data.projects, isLoading: false })
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to fetch projects', isLoading: false })
    }
  },
  
  fetchProject: async (id: string) => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.get(`/projects/${id}`)
      set({ currentProject: response.data.project, isLoading: false })
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to fetch project', isLoading: false })
    }
  },
  
  createProject: async (name: string, description?: string) => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.post('/projects', { name, description })
      const project = response.data.project
      set((state) => ({ 
        projects: [project, ...state.projects],
        isLoading: false 
      }))
      return project
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to create project', isLoading: false })
      throw error
    }
  },
  
  updateProject: async (id: string, data: Partial<Project>) => {
    try {
      const response = await api.put(`/projects/${id}`, data)
      set((state) => ({
        projects: state.projects.map(p => p.id === id ? response.data.project : p),
        currentProject: state.currentProject?.id === id ? response.data.project : state.currentProject
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to update project' })
    }
  },
  
  deleteProject: async (id: string) => {
    try {
      await api.delete(`/projects/${id}`)
      set((state) => ({
        projects: state.projects.filter(p => p.id !== id),
        currentProject: state.currentProject?.id === id ? null : state.currentProject
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to delete project' })
    }
  },
  
  uploadTemplate: async (projectId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    
    try {
      await api.post(`/projects/${projectId}/template`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      await get().fetchProject(projectId)
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to upload template' })
      throw error
    }
  },
  
  uploadFloorplan: async (projectId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    
    try {
      await api.post(`/projects/${projectId}/floorplan`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      await get().fetchProject(projectId)
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to upload floorplan' })
      throw error
    }
  },
  
  fetchFloorplan: async (projectId: string, floorplanId: string) => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.get(`/projects/${projectId}/floorplans/${floorplanId}`)
      set({ currentFloorplan: response.data.floorplan, isLoading: false })
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to fetch floorplan', isLoading: false })
    }
  },
  
  updateFloorplan: async (projectId: string, floorplanId: string, data: Partial<FloorPlan>) => {
    try {
      const response = await api.put(`/projects/${projectId}/floorplans/${floorplanId}`, data)
      set({ currentFloorplan: response.data.floorplan })
      
      // Update the floorplan in currentProject.floorplans if it exists
      set((state) => ({
        currentProject: state.currentProject ? {
          ...state.currentProject,
          floorplans: state.currentProject.floorplans?.map(fp => 
            fp.id === floorplanId ? response.data.floorplan : fp
          )
        } : null
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to update floorplan' })
      throw error
    }
  },
  
  deleteFloorplan: async (projectId: string, floorplanId: string) => {
    try {
      await api.delete(`/projects/${projectId}/floorplans/${floorplanId}`)
      
      // Remove from currentProject.floorplans
      set((state) => ({
        currentProject: state.currentProject ? {
          ...state.currentProject,
          floorplans: state.currentProject.floorplans?.filter(fp => fp.id !== floorplanId),
          floorplan_count: (state.currentProject.floorplan_count || 1) - 1
        } : null,
        currentFloorplan: state.currentFloorplan?.id === floorplanId ? null : state.currentFloorplan
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to delete floorplan' })
      throw error
    }
  },
  
  detectShapes: async (floorplanId: string, shapeType: string = 'auto') => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.post(`/processing/detect/${floorplanId}`, { shape_type: shapeType })
      const shapes = response.data.shapes
      
      // Update current floorplan with detected shapes
      set((state) => ({
        isLoading: false,
        currentFloorplan: state.currentFloorplan ? {
          ...state.currentFloorplan,
          shape_type: response.data.shape_type,
          extracted_data: shapes
        } : null
      }))
      
      return shapes
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Shape detection failed', isLoading: false })
      throw error
    }
  },
  
  runOCR: async (floorplanId: string) => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.post(`/processing/ocr/${floorplanId}`)
      const results = response.data.results
      
      set((state) => ({
        isLoading: false,
        currentFloorplan: state.currentFloorplan ? {
          ...state.currentFloorplan,
          status: 'completed',
          extracted_data: results
        } : null
      }))
      
      return results
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'OCR failed', isLoading: false })
      throw error
    }
  },
  
  ocrRegion: async (floorplanId: string, region: { x: number; y: number; width: number; height: number }) => {
    try {
      const response = await api.post(`/processing/ocr-region/${floorplanId}`, region)
      const result = response.data.result
      
      set((state) => ({
        currentFloorplan: state.currentFloorplan ? {
          ...state.currentFloorplan,
          extracted_data: [...(state.currentFloorplan.extracted_data || []), result]
        } : null
      }))
      
      return result
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'OCR failed' })
      throw error
    }
  },
  
  updateExtractedData: async (dataId: string, manualText?: string, quantity?: number) => {
    try {
      const payload: { manual_text?: string; quantity?: number } = {}
      if (manualText !== undefined) payload.manual_text = manualText
      if (quantity !== undefined) payload.quantity = quantity
      
      const response = await api.put(`/processing/data/${dataId}`, payload)
      const updated = response.data.result
      
      set((state) => ({
        currentFloorplan: state.currentFloorplan ? {
          ...state.currentFloorplan,
          extracted_data: state.currentFloorplan.extracted_data?.map(
            d => d.id === dataId ? updated : d
          )
        } : null
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to update data' })
    }
  },
  
  deleteExtractedData: async (dataId: string) => {
    try {
      await api.delete(`/processing/data/${dataId}`)
      
      set((state) => ({
        currentFloorplan: state.currentFloorplan ? {
          ...state.currentFloorplan,
          extracted_data: state.currentFloorplan.extracted_data?.filter(d => d.id !== dataId)
        } : null
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to delete data' })
    }
  },
  
  clearError: () => set({ error: null })
}))

