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
  nasPhotos?: string[]
  nasSourcePath?: string
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
  nasParentBucket?: string
  location?: string
  stage: string
  status: string
  owner?: { name: string }
  totalRecords?: number
  todayRecords?: number
  nasFileCount?: number
  nasLastModified?: string
  nasSyncedAt?: string
  nasFolderName?: string
}

function physicalNasBucketCode(bucketCode: string): string {
  const b = bucketCode.trim()
  if (b.toLowerCase().startsWith('__standalone:')) {
    return b.slice('__standalone:'.length).trim()
  }
  return b
}

function findBucketSiteProject(
  projects: WaProject[],
  bucketCode: string,
  folderName: string,
): WaProject | undefined {
  const key = folderName.trim().toUpperCase()
  const parentKey = physicalNasBucketCode(bucketCode).toUpperCase()
  return projects.find((p) => {
    const codeOk =
      (p.code || '').toUpperCase() === key || (p.nasFolderName || '').toUpperCase() === key
    if (!codeOk) return false
    const pb = (p.nasParentBucket || '').trim().toUpperCase()
    if (!pb) return true
    return (
      pb === parentKey ||
      pb === bucketCode.toUpperCase() ||
      physicalNasBucketCode(pb).toUpperCase() === parentKey
    )
  })
}

export interface NasStatus {
  degraded?: boolean
  foldersCacheAgeSec?: number | null
  enabled: boolean
  connected: boolean
  watchDir: string
  foldersFound: number
  filesFound: number
  rootFolderNames?: string[]
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
  nasStatusLoading: boolean
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
  deleteNasRootFolder: (
    folderName: string
  ) => Promise<{ quarantined?: boolean; alreadyRemoved?: boolean; message?: string }>
  syncNasFromDrive: () => Promise<{
    created: string[]
    removed: string[]
    foldersCreated: string[]
    totalCreated: number
    totalRemoved: number
    projectsRealigned?: number
    skipped?: boolean
    skipReason?: string
  }>
  syncNasBucket: (bucketCode: string) => Promise<{
    created: string[]
    updated: number
    scanned: number
  }>
  linkNasBucketFolder: (
    bucketCode: string,
    folderName: string,
  ) => Promise<{ projectId: string; code: string; created: boolean; updated: boolean }>
  fetchNasRootBuckets: () => Promise<
    Array<{ bucketCode: string; nasName: string; childCount?: number }>
  >
  fetchNasBucketSites: (
    bucketCode: string,
    opts?: { cacheOnly?: boolean; liveScan?: boolean; timeoutMs?: number },
  ) => Promise<{
    sites: WaProject[]
    staleFromCache?: boolean
    hint?: string
  }>
  createProject: (data: {
    code: string
    name?: string
    location?: string
    stage: string
    parentBucketCode?: string
  }) => Promise<void>
  deleteProject: (
    id: string,
    deleteNasFolder?: boolean
  ) => Promise<{ message?: string; nasQuarantined?: boolean; code?: string }>
  updateProject: (
    id: string,
    data: {
      code?: string
      nasFolderName?: string
      location?: string
      stage?: string
      status?: string
      syncNas?: boolean
    }
  ) => Promise<WaProject>
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
  nasStatusLoading: false,
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
      const { data } = await api.get('/wa/projects', { timeout: 60000 })
      set({ projects: data })
    } catch (err: unknown) {
      set({ projects: [] })
      const ax = err as { code?: string; message?: string; response?: { status?: number } }
      const status = ax.response?.status
      const isLocalDev = import.meta.env.DEV && !import.meta.env.VITE_API_URL?.trim()
      const msg =
        ax.code === 'ECONNABORTED'
          ? 'Project list timed out (NAS may be slow). Retry or click Sync NAS.'
          : status === 401
            ? 'Session expired — please sign in again'
            : status === 404
              ? 'Project list API not found — deploy the latest Sign House backend or check the API gateway.'
              : isLocalDev
                ? 'Could not load projects. Ensure the backend is running (local default port 5002).'
                : 'Could not load projects. Check that the API server is up and reachable.'
      import('react-hot-toast').then(({ default: toast }) => toast.error(msg))
    } finally {
      set({ loading: false })
    }
  },

  fetchProjectRecords: async (projectId, params = {}) => {
    try {
      const { data } = await api.get(`/wa/projects/${projectId}/records`, {
        params,
        timeout: 30000,
      })
      set({ records: data.records || data })
    } catch {
      // Keep prior records on timeout — NAS slowness must not blank the detail page.
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
    set({ nasStatusLoading: true })
    try {
      const { data } = await api.get('/wa/nas/status', { timeout: 15000 })
      set({ nasStatus: data })
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 401 || status === 422) {
        set({ nasStatus: null })
        return
      }
      const timedOut =
        (err as { code?: string })?.code === 'ECONNABORTED'
      set({
        nasStatus: {
          enabled: true,
          connected: false,
          watchDir: '',
          foldersFound: 0,
          filesFound: 0,
          mountHint: timedOut
            ? 'NAS status request timed out — backend may be scanning SMB; refresh in a moment or remount NAS.'
            : 'Could not reach the backend at port 5002. Start: cd backend && python run.py --all',
        },
      })
    } finally {
      set({ nasStatusLoading: false })
    }
  },

  deleteNasRootFolder: async (folderName) => {
    const encoded = encodeURIComponent(folderName)
    const { data } = await api.delete<{
      quarantined?: boolean
      alreadyRemoved?: boolean
      message?: string
    }>(`/wa/nas/root-folders/${encoded}`)
    return data
  },

  syncNasFromDrive: async () => {
    const syncTimeout = { timeout: 300000 }
    let data: {
      projectsCreated?: string[]
      projectsRemoved?: string[]
      projectsRealigned?: number
      foldersCreated?: string[]
      recordsImported?: number
      recordsRemoved?: number
      totalCreated?: number
      skipped?: boolean
      reason?: string
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
      foldersCreated: data.foldersCreated || [],
      totalCreated: data.recordsImported ?? data.totalCreated ?? 0,
      totalRemoved: data.recordsRemoved ?? 0,
      projectsRealigned: data.projectsRealigned ?? 0,
      skipped: Boolean(data.skipped),
      skipReason: data.reason,
    }
  },

  syncNasBucket: async (bucketCode) => {
    const { data } = await api.post(
      '/wa/nas/sync-bucket',
      { bucketCode },
      { timeout: 120000 },
    )
    return {
      created: (data.created as string[]) || [],
      updated: (data.updated as number) || 0,
      scanned: (data.scanned as number) || 0,
    }
  },

  linkNasBucketFolder: async (bucketCode, folderName) => {
    const folder = folderName.trim()
    const finish = (project: WaProject, created: boolean, updated: boolean) => ({
      projectId: project.id,
      code: project.code || folder,
      created,
      updated,
    })

    try {
      const { data } = await api.post(
        '/wa/nas/link-bucket-folder',
        { bucketCode, folderName: folder },
        { timeout: 120000 },
      )
      if (data.ok === false) {
        throw new Error((data.error as string) || 'Link failed')
      }
      return {
        projectId: data.projectId as string,
        code: (data.code as string) || folder,
        created: Boolean(data.created),
        updated: Boolean(data.updated),
      }
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status !== 404) throw err
    }

    try {
      await api.post('/wa/nas/sync-bucket', { bucketCode }, { timeout: 120000 })
    } catch {
      // sync-bucket may be missing on very old backends
    }

    const loadProjects = async (): Promise<WaProject[]> => {
      try {
        const { data } = await api.get<WaProject[]>('/wa/projects')
        return data
      } catch {
        return []
      }
    }

    let projects = await loadProjects()
    let match = findBucketSiteProject(projects, bucketCode, folder)
    if (match) return finish(match, false, true)

    try {
      const { data: created } = await api.post<WaProject>('/wa/admin/projects', {
        code: folder,
        name: folder,
        parentBucketCode: bucketCode,
      })
      set((state) => ({
        projects: [created, ...state.projects.filter((p) => p.id !== created.id)],
      }))
      return finish(created, true, false)
    } catch (createErr: unknown) {
      const cStatus = (createErr as { response?: { status?: number } })?.response?.status
      if (cStatus === 409) {
        projects = await loadProjects()
        match = findBucketSiteProject(projects, bucketCode, folder)
        if (match) return finish(match, false, true)
      }
      const msg =
        (createErr as { response?: { data?: { error?: string } } })?.response?.data?.error
      throw new Error(
        msg ||
          'Link failed (server missing link API). Deploy the latest backend, or create the project in Manage Projects.',
      )
    }
  },

  fetchNasRootBuckets: async () => {
    try {
      const { data } = await api.get('/wa/projects/nas-root-buckets', { timeout: 45000 })
      if (data.ok === false) return []
      return (data.buckets || []) as Array<{
        bucketCode: string
        nasName: string
        childCount?: number
      }>
    } catch {
      return []
    }
  },

  fetchNasBucketSites: async (bucketCode, opts) => {
    const { data } = await api.get('/wa/projects/nas-bucket-sites', {
      params: {
        bucket: bucketCode,
        ...(opts?.liveScan ? { liveScan: '1' } : { sync: '0' }),
        ...(opts?.cacheOnly ? { cacheOnly: '1' } : {}),
      },
      timeout: opts?.timeoutMs ?? 60000,
    })
    if (data.ok === false) {
      throw new Error((data.error as string) || 'NAS bucket list failed')
    }
    const sites = (data.sites || []) as Array<Record<string, unknown>>
    return {
      sites: sites.map((row) => ({
        id: (row.projectId as string) || `nas:${row.folderName}`,
        code: (row.code as string) || (row.folderName as string) || '',
        nasFolderName: (row.nasFolderName as string) || (row.folderName as string) || '',
        status: (row.status as string) || 'active',
        stage: 'active',
        totalRecords: (row.totalRecords as number) ?? 0,
        todayRecords: (row.todayRecords as number) ?? 0,
        location: row.location as string | undefined,
        nasParentBucket: row.nasParentBucket as string | undefined,
        nasFileCount: (row.nasFileCount as number) ?? undefined,
      })) as WaProject[],
      staleFromCache: Boolean(data.staleFromCache),
      hint: (data.hint as string) || undefined,
    }
  },

  createProject: async (projData) => {
    const { data } = await api.post('/wa/admin/projects', projData)
    set((state) => ({
      projects: [data as WaProject, ...state.projects.filter((p) => p.id !== data.id)],
    }))
    return data
  },

  deleteProject: async (id, deleteNasFolder = false) => {
    const { data } = await api.delete<{ message?: string; nasQuarantined?: boolean; code?: string }>(
      `/wa/admin/projects/${id}`,
      { data: { deleteNasFolder } }
    )
    set((state) => ({
      projects: state.projects.filter((p) => p.id !== id),
    }))
    return data
  },

  updateProject: async (id, patch) => {
    const { data } = await api.patch(`/wa/admin/projects/${id}`, patch)
    const updated = data as WaProject
    set((state) => ({
      projects: state.projects.map((p) => (p.id === id ? updated : p)),
    }))
    return updated
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
