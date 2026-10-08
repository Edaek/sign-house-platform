import { create } from 'zustand'
import api from '../lib/api'

export type WaRecordStatus = 'incomplete' | 'followup' | 'awaiting_review' | 'completed' | 'voided'
export type ConfidenceLevel = 'green' | 'yellow' | 'red' | 'gray'

export interface ExtractedField {
  name: string
  value: string
  confidence: string
}

export interface FollowUpEntry {
  question: string
  answer?: string
  timestamp: string
  round: number
}

export interface StatusEntry {
  from: string
  to: string
  timestamp: string
  reason?: string
}

export interface WaRecord {
  id: string
  referenceNumber: string
  status: WaRecordStatus
  type: string
  rawMessage: string
  /** WhatsApp classify trailing note (API may fill when rawMessage is [Pool media]) */
  remark?: string
  senderPhone: string
  senderName?: string
  photos: string[]
  hasMedia?: boolean
  mediaType?: string
  extractedFields: ExtractedField[]
  followUpThread: FollowUpEntry[]
  statusHistory: StatusEntry[]
  createdAt: string
}

export interface WaProject {
  id: string
  code: string
  name: string
  location?: string
  stage: string
  status: string
  owner?: { name: string }
  totalRecords?: number
  todayRecords?: number
  nasFileCount?: number
  nasLastModified?: string
  nasSyncedAt?: string
}

export interface NasStatus {
  enabled: boolean
  connected: boolean
  watchDir: string
  foldersFound: number
  filesFound: number
  disconnectReason?: string
  mountHint?: string
  lastAutoSyncAt?: string
  lastRecordsImported?: number
  autoSyncIntervalSec?: number
}

export interface PoolImage {
  id: string
  phone: string
  senderName?: string
  imagePath?: string
  fileName?: string
  mediaType?: 'image' | 'document' | 'video' | 'file' | string
  mimeType?: string
  downloadFailed?: boolean
  caption?: string
  messageId: string
  projectId?: string
  projectCode?: string
  projectName?: string
  assignedBy?: string
  assignedAt?: string
  createdAt: string
}

export interface PoolStats {
  totalUnassigned: number
  totalAssigned: number
  bySender: Array<{
    id: string
    count: number
    senderName?: string
    latestAt: string
  }>
}

export interface DashboardStats {
  todayIntake: number
  pendingCompletion: number
  awaitingReview: number
  completedToday: number
  followUpOverdue: number
}

export interface KeywordData {
  id: string
  term: string
  type: string
  synonyms: string[]
  isActive: boolean
}

export interface TemplateData {
  id: string
  typeName: string
  projectId?: { code: string; name: string }
  fields: Array<{ name: string; type: string; required: boolean }>
  isActive: boolean
}

export interface SystemStatus {
  connected: boolean
  status: string
  phoneNumber?: string
  tokenBalance?: number
  plan?: string
}

export interface InfraStatus {
  mongo: 'ok' | 'error' | 'checking'
  ollama: 'ok' | 'error' | 'checking'
  ollamaBaseUrl?: string
  ollamaTextModel?: string
  ollamaVisionModel?: string
  ollamaError?: string | null
}

interface WaStore {
  dashboardStats: DashboardStats | null
  recentRecords: WaRecord[]
  projects: WaProject[]
  records: WaRecord[]
  poolImages: PoolImage[]
  poolStats: PoolStats | null
  keywords: KeywordData[]
  templates: TemplateData[]
  systemStatus: SystemStatus | null
  infraStatus: InfraStatus
  nasStatus: NasStatus | null
  loading: boolean

  fetchDashboard: () => Promise<void>
  fetchProjects: () => Promise<void>
  fetchProjectRecords: (projectId: string, params?: Record<string, string>) => Promise<void>
  fetchPoolImages: (params?: Record<string, string>) => Promise<void>
  fetchPoolStats: () => Promise<void>
  assignImages: (imageIds: string[], projectId: string) => Promise<{ assigned: number; projectCode: string }>
  retryDownload: (imageIds: string[]) => Promise<{ succeeded: number }>
  deletePoolImages: (imageIds: string[]) => Promise<{ deleted: number }>
  searchRecords: (params: Record<string, string>) => Promise<WaRecord[]>
  fetchKeywords: () => Promise<void>
  createKeyword: (data: { term: string; type: string; synonyms: string[] }) => Promise<void>
  deleteKeyword: (id: string) => Promise<void>
  fetchTemplates: () => Promise<void>
  createTemplate: (data: { typeName: string; fields: Array<{ name: string; type: string; required: boolean }> }) => Promise<void>
  fetchSystemStatus: () => Promise<void>
  fetchInfraStatus: () => Promise<void>
  fetchNasStatus: () => Promise<void>
  syncNasFromDrive: () => Promise<{
    created: string[]
    removed: string[]
    totalCreated: number
    totalRemoved: number
  }>
  createProject: (data: { code: string; name: string; location?: string; stage: string }) => Promise<void>
  deleteProject: (id: string, deleteNasFolder?: boolean) => Promise<void>
  confirmRecord: (id: string) => Promise<void>
  voidRecord: (id: string, reason: string) => Promise<void>
  requestInfo: (id: string, question: string) => Promise<void>
  updateRecordField: (id: string, field: string, value: string) => Promise<void>
}

export const useWaStore = create<WaStore>((set) => ({
  dashboardStats: null,
  recentRecords: [],
  projects: [],
  records: [],
  poolImages: [],
  poolStats: null,
  keywords: [],
  templates: [],
  systemStatus: null,
  infraStatus: { mongo: 'checking', ollama: 'checking' },
  nasStatus: null,
  loading: false,

  fetchDashboard: async () => {
    set({ loading: true })
    try {
      const [statsRes, recordsRes] = await Promise.all([
        api.get('/wa/dashboard/stats'),
        api.get('/wa/dashboard/recent'),
      ])
      set({ dashboardStats: statsRes.data, recentRecords: recordsRes.data.records || [] })
    } finally {
      set({ loading: false })
    }
  },

  fetchProjects: async () => {
    set({ loading: true })
    try {
      const { data } = await api.get('/wa/projects')
      set({ projects: data })
    } finally {
      set({ loading: false })
    }
  },

  fetchProjectRecords: async (projectId, params = {}) => {
    set({ loading: true, records: [] })
    try {
      const { data } = await api.get(`/wa/projects/${projectId}/records`, { params })
      set({ records: data.records || data })
    } finally {
      set({ loading: false })
    }
  },

  fetchPoolImages: async (params = {}) => {
    set({ loading: true })
    try {
      const { data } = await api.get('/wa/image-pool', { params: { limit: '200', ...params } })
      set({ poolImages: data.images || [] })
    } finally {
      set({ loading: false })
    }
  },

  fetchPoolStats: async () => {
    const { data } = await api.get('/wa/image-pool', { params: { mode: 'stats' } })
    set({ poolStats: data })
  },

  assignImages: async (imageIds, projectId) => {
    const { data } = await api.post('/wa/image-pool/assign', { imageIds, projectId })
    return data
  },

  retryDownload: async (imageIds) => {
    const { data } = await api.post('/wa/image-pool/retry-download', { imageIds })
    return data
  },

  deletePoolImages: async (imageIds) => {
    const { data } = await api.post('/wa/image-pool/delete', { imageIds })
    return data
  },

  searchRecords: async (params) => {
    const { data } = await api.get('/wa/search', { params })
    return data.records || []
  },

  fetchKeywords: async () => {
    const { data } = await api.get('/wa/admin/keywords')
    set({ keywords: data })
  },

  createKeyword: async (kwData) => {
    await api.post('/wa/admin/keywords', kwData)
  },

  deleteKeyword: async (id) => {
    await api.delete(`/wa/admin/keywords?id=${id}`)
  },

  fetchTemplates: async () => {
    const { data } = await api.get('/wa/admin/templates')
    set({ templates: data })
  },

  createTemplate: async (tplData) => {
    await api.post('/wa/admin/templates', tplData)
  },

  fetchSystemStatus: async () => {
    try {
      const { data } = await api.get('/wa/admin/system/status')
      set({ systemStatus: data })
    } catch {
      set({ systemStatus: { connected: false, status: 'unreachable' } })
    }
  },

  fetchInfraStatus: async () => {
    try {
      const { data } = await api.get('/wa/admin/system/infra')
      set({ infraStatus: data })
    } catch {
      set({ infraStatus: { mongo: 'error', ollama: 'error' } })
    }
  },

  fetchNasStatus: async () => {
    try {
      const { data } = await api.get('/wa/nas/status')
      set({ nasStatus: data })
    } catch {
      set({ nasStatus: null })
    }
  },

  syncNasFromDrive: async () => {
    const syncTimeout = { timeout: 300000 }
    let data: {
      projectsCreated?: string[]
      projectsRemoved?: string[]
      recordsImported?: number
      recordsRemoved?: number
      totalCreated?: number
    }
    try {
      ;({ data } = await api.post('/wa/nas/sync-bidirectional', {}, syncTimeout))
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status !== 404) throw err
      await api.post('/wa/nas/sync-projects', {}, syncTimeout)
      ;({ data } = await api.post('/wa/nas/import-all', {}, syncTimeout))
    }
    try {
      const { data: projects } = await api.get('/wa/projects')
      set({ projects })
    } catch {
      // Sync may have succeeded even if list refresh fails (slow NAS / backend restart)
    }
    return {
      created: data.projectsCreated || [],
      removed: data.projectsRemoved || [],
      totalCreated: data.recordsImported ?? data.totalCreated ?? 0,
      totalRemoved: data.recordsRemoved ?? 0,
    }
  },

  createProject: async (projData) => {
    const { data } = await api.post('/wa/admin/projects', projData)
    return data
  },

  deleteProject: async (id, deleteNasFolder = false) => {
    await api.delete(`/wa/admin/projects/${id}`, { data: { deleteNasFolder } })
  },

  confirmRecord: async (id) => {
    await api.post(`/wa/records/${id}/confirm`)
  },

  voidRecord: async (id, reason) => {
    await api.post(`/wa/records/${id}/void`, { reason })
  },

  requestInfo: async (id, question) => {
    await api.post(`/wa/records/${id}/request-info`, { question })
  },

  updateRecordField: async (id, field, value) => {
    await api.patch(`/wa/records/${id}`, { field, value })
  },
}))
