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
  shape_data?: {
    radius?: number
    center_x?: number
    center_y?: number
  }
  extracted_text: string | null
  confidence: number | null
  quantity: number
  merged_count?: number
  original_shape_indices?: number[]
  all_bounding_boxes?: Array<{
    x: number
    y: number
    width: number
    height: number
    shape_type: string
    shape_data?: {
      radius?: number
      center_x?: number
      center_y?: number
    }
  }>
  is_manual: boolean
  manual_text: string | null
  display_text: string | null
  detection_method?: 'auto' | 'manual' | 'learned'
  template_id?: string | null
  _template_saved?: boolean
}

interface ShapeTemplate {
  id: string
  shape_type: string
  image_path: string
  width: number
  height: number
  color_profile: Record<string, number | number[]> | null
  source_floorplan_id: string | null
  extracted_text: string | null
  created_by: string | null
  is_active: boolean
  match_count: number
  created_at: string | null
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

interface CropRegion {
  x: number
  y: number
  width: number
  height: number
  name: string
}

interface ProcessingFile {
  filename: string
  status: 'pending' | 'uploading' | 'converting' | 'detecting' | 'ocr' | 'completed' | 'error'
  progress: number
  error: string | null
  floorplan_ids: string[]
  pages_total: number
  pages_processed: number
  shapes_detected: number
  started_at: string | null
  completed_at: string | null
}

interface BatchUploadJob {
  id: string
  job_id: string
  project_id: string
  user_id: string
  status: 'pending' | 'processing' | 'completed' | 'error'
  total_files: number
  processed_files: number
  files: ProcessingFile[]
  created_at: string
  updated_at: string
  completed_at: string | null
}

interface ProjectState {
  projects: Project[]
  currentProject: Project | null
  currentFloorplan: FloorPlan | null
  isLoading: boolean
  error: string | null
  
  // Batch upload state
  currentBatchJob: BatchUploadJob | null
  isBatchUploading: boolean

  // Shape templates (self-learning)
  shapeTemplates: ShapeTemplate[]
  
  fetchProjects: () => Promise<void>
  fetchProject: (id: string) => Promise<void>
  createProject: (name: string, description?: string) => Promise<Project>
  updateProject: (id: string, data: Partial<Project>) => Promise<void>
  deleteProject: (id: string) => Promise<void>
  
  uploadTemplate: (projectId: string, file: File) => Promise<void>
  uploadFloorplan: (projectId: string, file: File) => Promise<void>
  uploadFloorplans: (projectId: string, files: File[], detectionMode?: 'fast' | 'accurate') => Promise<BatchUploadJob>
  pollBatchStatus: (projectId: string, jobId: string) => Promise<BatchUploadJob>
  fetchActiveBatchJob: (projectId: string) => Promise<BatchUploadJob | null>
  clearBatchJob: () => void
  
  fetchFloorplan: (projectId: string, floorplanId: string) => Promise<void>
  updateFloorplan: (projectId: string, floorplanId: string, data: Partial<FloorPlan>) => Promise<void>
  deleteFloorplan: (projectId: string, floorplanId: string) => Promise<void>
  splitFloorplan: (projectId: string, floorplanId: string, regions: CropRegion[], deleteOriginal?: boolean) => Promise<FloorPlan[]>
  
  detectShapes: (floorplanId: string, shapeType?: string, mode?: 'fast' | 'accurate') => Promise<ExtractedData[]>
  runOCR: (floorplanId: string) => Promise<ExtractedData[]>
  ocrRegion: (floorplanId: string, region: { x: number; y: number; width: number; height: number; shape_type?: string; shape_data?: { center_x: number; center_y: number; radius: number } }) => Promise<ExtractedData>
  updateExtractedData: (dataId: string, manualText?: string, quantity?: number) => Promise<void>
  deleteExtractedData: (dataId: string) => Promise<void>

  fetchShapeTemplates: () => Promise<void>
  deleteShapeTemplate: (templateId: string) => Promise<void>
  toggleShapeTemplate: (templateId: string, isActive: boolean) => Promise<void>
  
  clearError: () => void
}

export const useProjectStore = create<ProjectState>()((set, get) => ({
  projects: [],
  currentProject: null,
  currentFloorplan: null,
  isLoading: false,
  error: null,
  currentBatchJob: null,
  isBatchUploading: false,
  shapeTemplates: [],
  
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
      const updatedProject = response.data.project
      set((state) => ({
        projects: state.projects.map(p => p.id === id ? { ...p, ...updatedProject } : p),
        currentProject: state.currentProject?.id === id 
          ? { ...state.currentProject, ...updatedProject }
          : state.currentProject
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
  
  uploadFloorplans: async (projectId: string, files: File[], detectionMode: 'fast' | 'accurate' = 'accurate') => {
    set({ isBatchUploading: true, error: null })

    const formData = new FormData()
    files.forEach(file => {
      formData.append('files', file)
    })
    formData.append('detection_mode', detectionMode)
    
    try {
      const response = await api.post(`/processing/batch-upload/${projectId}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      const job = response.data.job as BatchUploadJob
      set({ currentBatchJob: job })
      return job
    } catch (error: any) {
      set({ 
        error: error.response?.data?.error || 'Failed to upload floorplans',
        isBatchUploading: false 
      })
      throw error
    }
  },
  
  pollBatchStatus: async (projectId: string, jobId: string) => {
    try {
      const response = await api.get(`/processing/batch-upload/${projectId}/job/${jobId}`)
      const job = response.data.job as BatchUploadJob
      set({ currentBatchJob: job })
      
      // If job is completed or errored, stop uploading state and refresh project
      if (job.status === 'completed' || job.status === 'error') {
        set({ isBatchUploading: false })
        await get().fetchProject(projectId)
      }
      
      return job
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to get batch status' })
      throw error
    }
  },
  
  clearBatchJob: () => {
    set({ currentBatchJob: null, isBatchUploading: false })
  },
  
  fetchActiveBatchJob: async (projectId: string) => {
    try {
      const response = await api.get(`/processing/batch-upload/${projectId}/status`)
      const job = response.data.job as BatchUploadJob
      
      // Only restore job if it's still in progress
      if (job.status === 'pending' || job.status === 'processing') {
        set({ currentBatchJob: job, isBatchUploading: true })
        return job
      }
      
      return null
    } catch {
      // No active job found - this is expected behavior, not an error
      return null
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
  
  splitFloorplan: async (_projectId: string, floorplanId: string, regions: CropRegion[], deleteOriginal = false) => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.post(`/processing/split/${floorplanId}`, {
        regions,
        delete_original: deleteOriginal
      })
      
      const newFloorplans = response.data.floorplans
      
      // Update currentProject with new floorplans
      set((state) => {
        if (!state.currentProject) return { isLoading: false }
        
        let updatedFloorplans = [...(state.currentProject.floorplans || [])]
        
        // Remove original if deleted
        if (deleteOriginal) {
          updatedFloorplans = updatedFloorplans.filter(fp => fp.id !== floorplanId)
        }
        
        // Add new floorplans
        updatedFloorplans = [...updatedFloorplans, ...newFloorplans]
        
        // Sort by floor_number
        updatedFloorplans.sort((a, b) => a.floor_number - b.floor_number)
        
        return {
          isLoading: false,
          currentProject: {
            ...state.currentProject,
            floorplans: updatedFloorplans,
            floorplan_count: updatedFloorplans.length
          },
          currentFloorplan: deleteOriginal && state.currentFloorplan?.id === floorplanId
            ? null
            : state.currentFloorplan
        }
      })
      
      return newFloorplans
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to split floorplan', isLoading: false })
      throw error
    }
  },
  
  detectShapes: async (floorplanId: string, shapeType: string = 'auto', mode: 'fast' | 'accurate' = 'accurate') => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.post(`/processing/detect/${floorplanId}`, { shape_type: shapeType, mode })
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
  
  ocrRegion: async (floorplanId: string, region: { x: number; y: number; width: number; height: number; shape_type?: string; shape_data?: { center_x: number; center_y: number; radius: number } }) => {
    try {
      const response = await api.post(`/processing/ocr-region/${floorplanId}`, region)
      const result = response.data.result
      result._template_saved = response.data.template_saved || false
      
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
  
  fetchShapeTemplates: async () => {
    try {
      const response = await api.get('/processing/templates', { params: { active_only: 'false' } })
      set({ shapeTemplates: response.data.templates })
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to fetch shape templates' })
    }
  },

  deleteShapeTemplate: async (templateId: string) => {
    try {
      await api.delete(`/processing/templates/${templateId}`)
      set((state) => ({
        shapeTemplates: state.shapeTemplates.map(t =>
          t.id === templateId ? { ...t, is_active: false } : t
        )
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to delete template' })
    }
  },

  toggleShapeTemplate: async (templateId: string, isActive: boolean) => {
    try {
      await api.put(`/processing/templates/${templateId}`, { is_active: isActive })
      set((state) => ({
        shapeTemplates: state.shapeTemplates.map(t =>
          t.id === templateId ? { ...t, is_active: isActive } : t
        )
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.error || 'Failed to update template' })
    }
  },

  clearError: () => set({ error: null })
}))

