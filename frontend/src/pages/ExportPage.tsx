import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { 
  ChevronLeft,
  Download,
  FileSpreadsheet,
  FileText,
  CheckCircle,
  AlertTriangle,
  Table,
  ArrowRight,
  Save
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import api, { saveTemplateMapping, getTemplateMapping } from '../lib/api'
import toast from 'react-hot-toast'
import clsx from 'clsx'

interface ExportPreview {
  project: {
    id: string
    name: string
    status: string
  }
  columns: { name: string; column: number; letter: string }[]
  data: {
    floor_number: number
    floor_name: string
    shape_index: number
    text: string
    quantity: number
    merged_count?: number
    confidence: number
    is_manual: boolean
  }[]
  total_items: number
  summary?: {
    text: string
    total_quantity: number
    floor_count: number
    floors: number[]
    floor_details: {
      floor_number: number
      floor_name: string
      quantity: number
    }[]
  }[]
  summary_stats?: {
    unique_items: number
    total_floors: number
  }
}

export default function ExportPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { currentProject, fetchProject } = useProjectStore()
  const [preview, setPreview] = useState<ExportPreview | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [exportFormat, setExportFormat] = useState<'excel' | 'csv'>('excel')
  const [includeMetadata, setIncludeMetadata] = useState(true)
  const [floorMapping, setFloorMapping] = useState<Record<string, string>>({})
  const [showMappingUI, setShowMappingUI] = useState(false)
  const [isSavingMapping, setIsSavingMapping] = useState(false)
  
  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
      fetchPreview()
      loadTemplateMapping()
    }
  }, [projectId])
  
  useEffect(() => {
    // Show mapping UI if template exists but no mapping configured
    if (currentProject?.template && Object.keys(floorMapping).length === 0 && exportFormat === 'excel') {
      setShowMappingUI(true)
    }
  }, [currentProject?.template, floorMapping, exportFormat])
  
  const loadTemplateMapping = async () => {
    if (!projectId) return
    
    try {
      const response = await getTemplateMapping(projectId)
      if (response.floor_mapping) {
        setFloorMapping(response.floor_mapping)
      }
    } catch (error) {
      // Template might not exist or no mapping yet, that's okay
      console.log('No template mapping found')
    }
  }
  
  const handleSaveMapping = async () => {
    if (!projectId) return
    
    setIsSavingMapping(true)
    try {
      await saveTemplateMapping(projectId, floorMapping)
      toast.success('Floor mapping saved!')
      setShowMappingUI(false)
    } catch (error) {
      toast.error('Failed to save floor mapping')
    }
    setIsSavingMapping(false)
  }
  
  const handleFloorMappingChange = (floorNumber: string, columnName: string) => {
    setFloorMapping(prev => ({
      ...prev,
      [floorNumber]: columnName
    }))
  }
  
  // Get available floor columns from template (filter out non-floor columns)
  const getFloorColumns = () => {
    if (!preview?.columns) return []
    
    // Filter columns that look like floor columns (contain 'F' or 'Floor')
    return preview.columns.filter(col => 
      col.name.includes('/F') || col.name.includes('Floor') || col.name.match(/\d+F/i)
    )
  }
  
  // Get unique floors from data
  const getUniqueFloors = () => {
    if (!preview?.data) return []
    
    const floors = new Map()
    preview.data.forEach(item => {
      if (!floors.has(item.floor_number)) {
        floors.set(item.floor_number, item.floor_name)
      }
    })
    
    return Array.from(floors.entries()).map(([number, name]) => ({
      floor_number: number,
      floor_name: name as string
    }))
  }
  
  const fetchPreview = async () => {
    if (!projectId) return
    
    setIsLoading(true)
    try {
      const response = await api.get(`/export/preview/${projectId}`)
      setPreview(response.data)
    } catch (error) {
      toast.error('Failed to load export preview')
    }
    setIsLoading(false)
  }
  
  const handleExport = async () => {
    if (!projectId) return
    
    try {
      const endpoint = exportFormat === 'excel' 
        ? `/export/excel/${projectId}`
        : `/export/csv/${projectId}`
      
      const response = await api.post(endpoint, 
        { include_metadata: includeMetadata },
        { responseType: 'blob' }
      )
      
      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `${currentProject?.name || 'export'}.${exportFormat === 'excel' ? 'xlsx' : 'csv'}`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      
      toast.success('Export downloaded!')
    } catch {
      toast.error('Export failed')
    }
  }
  
  const incompleteFoors = currentProject?.floorplans?.filter(fp => fp.status !== 'completed') || []
  
  if (isLoading && !preview) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }
  
  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <Link 
          to={`/project/${projectId}`}
          className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white mb-4 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Project
        </Link>
        
        <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">Export Data</h1>
        <p className="text-slate-600 dark:text-slate-400 mt-1">
          Review and export extracted data from {currentProject?.name}
        </p>
      </div>
      
      {/* Warning for incomplete floors */}
      {incompleteFoors.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-6 p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-start gap-3"
        >
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-amber-200 font-medium">Some floors are not completed</p>
            <p className="text-amber-200/70 text-sm mt-1">
              {incompleteFoors.length} floor(s) still pending: {incompleteFoors.map(f => f.floor_name).join(', ')}
            </p>
          </div>
        </motion.div>
      )}
      
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Export Options */}
        <div className="lg:col-span-1 space-y-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="card p-6"
          >
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Export Format</h2>
            
            <div className="space-y-3">
              <button
                onClick={() => setExportFormat('excel')}
                className={clsx(
                  'w-full p-4 rounded-lg border-2 text-left transition-all',
                  exportFormat === 'excel'
                    ? 'border-sign-500 bg-sign-500/10'
                    : 'border-slate-300 hover:border-slate-400 dark:border-slate-700 dark:hover:border-slate-600'
                )}
              >
                  <div className="flex items-center gap-3">
                  <FileSpreadsheet className={clsx(
                    'w-6 h-6',
                    exportFormat === 'excel' ? 'text-sign-500 dark:text-sign-400' : 'text-slate-500 dark:text-slate-400'
                  )} />
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">Excel (.xlsx)</p>
                    <p className="text-sm text-slate-600 dark:text-slate-400">Uses template if uploaded</p>
                  </div>
                </div>
              </button>
              
              <button
                onClick={() => setExportFormat('csv')}
                className={clsx(
                  'w-full p-4 rounded-lg border-2 text-left transition-all',
                  exportFormat === 'csv'
                    ? 'border-sign-500 bg-sign-500/10'
                    : 'border-slate-300 hover:border-slate-400 dark:border-slate-700 dark:hover:border-slate-600'
                )}
              >
                  <div className="flex items-center gap-3">
                  <FileText className={clsx(
                    'w-6 h-6',
                    exportFormat === 'csv' ? 'text-sign-500 dark:text-sign-400' : 'text-slate-500 dark:text-slate-400'
                  )} />
                  <div>
                    <p className="font-medium text-slate-900 dark:text-white">CSV (.csv)</p>
                    <p className="text-sm text-slate-600 dark:text-slate-400">Simple comma-separated values</p>
                  </div>
                </div>
              </button>
            </div>
            
            <div className="mt-6">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeMetadata}
                  onChange={(e) => setIncludeMetadata(e.target.checked)}
                  className="w-4 h-4 rounded border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-800 text-sign-500 focus:ring-sign-500"
                />
                <span className="text-slate-700 dark:text-slate-300">Include position metadata</span>
              </label>
            </div>
            
            <button
              onClick={handleExport}
              disabled={!!(currentProject?.template && exportFormat === 'excel' && Object.keys(floorMapping).length === 0)}
              className="btn btn-primary w-full mt-6 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-5 h-5" />
              Download {exportFormat === 'excel' ? 'Excel' : 'CSV'}
            </button>
            
            {currentProject?.template && exportFormat === 'excel' && Object.keys(floorMapping).length === 0 && (
              <p className="text-xs text-amber-400 mt-2 text-center">
                Configure floor mapping first
              </p>
            )}
          </motion.div>
          
          {/* Floor Mapping Configuration */}
          {currentProject?.template && exportFormat === 'excel' && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 }}
              className="card p-6"
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Floor Mapping</h2>
                {Object.keys(floorMapping).length > 0 && (
                  <span className="text-xs text-emerald-400 flex items-center gap-1">
                    <CheckCircle className="w-3 h-3" />
                    Configured
                  </span>
                )}
              </div>
              
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
                Map your extracted floors to template columns
              </p>
              
              {!showMappingUI && Object.keys(floorMapping).length > 0 ? (
                <div className="space-y-2">
                  {Object.entries(floorMapping).map(([floor, column]) => {
                    const floorData = getUniqueFloors().find(f => f.floor_number.toString() === floor)
                    return (
                      <div key={floor} className="flex items-center gap-2 text-sm">
                        <span className="text-slate-700 dark:text-slate-300 font-medium">{floorData?.floor_name}</span>
                        <ArrowRight className="w-3 h-3 text-slate-400" />
                        <span className="text-sign-400 font-mono">{column}</span>
                      </div>
                    )
                  })}
                  <button
                    onClick={() => setShowMappingUI(true)}
                    className="text-sm text-sign-400 hover:text-sign-300 mt-3"
                  >
                    Edit mapping
                  </button>
                </div>
              ) : (
                <>
                  <div className="space-y-3 mb-4">
                    {getUniqueFloors().map(floor => (
                      <div key={floor.floor_number} className="space-y-1">
                        <label className="text-xs text-slate-600 dark:text-slate-400 font-medium">
                          {floor.floor_name}
                        </label>
                        <select
                          value={floorMapping[floor.floor_number] || ''}
                          onChange={(e) => handleFloorMappingChange(floor.floor_number.toString(), e.target.value)}
                          className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-white focus:ring-2 focus:ring-sign-500 focus:border-transparent"
                        >
                          <option value="">Select column...</option>
                          {getFloorColumns().map(col => (
                            <option key={col.name} value={col.name}>
                              {col.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </div>
                  
                  <button
                    onClick={handleSaveMapping}
                    disabled={isSavingMapping || Object.keys(floorMapping).length === 0}
                    className="btn btn-secondary w-full flex items-center justify-center gap-2 disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {isSavingMapping ? 'Saving...' : 'Save Mapping'}
                  </button>
                  
                  {Object.keys(floorMapping).length > 0 && (
                    <button
                      onClick={() => setShowMappingUI(false)}
                      className="text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 w-full mt-2"
                    >
                      Cancel
                    </button>
                  )}
                </>
              )}
            </motion.div>
          )}
          
          {/* Summary */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="card p-6"
          >
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Summary</h2>
            
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-slate-600 dark:text-slate-400">Total Items</span>
                <span className="text-slate-900 dark:text-white font-medium">{preview?.total_items || 0}</span>
              </div>
              {preview?.summary_stats && (
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">Unique Items</span>
                  <span className="text-emerald-500 dark:text-emerald-400 font-medium">{preview.summary_stats.unique_items}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-slate-600 dark:text-slate-400">Floors</span>
                <span className="text-slate-900 dark:text-white font-medium">{currentProject?.floorplans?.length || 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600 dark:text-slate-400">Template</span>
                <span className="text-slate-900 dark:text-white font-medium">
                  {currentProject?.template ? (
                    <span className="flex items-center gap-1 text-emerald-400">
                      <CheckCircle className="w-4 h-4" />
                      Loaded
                    </span>
                  ) : (
                    <span className="text-slate-500">None</span>
                  )}
                </span>
              </div>
            </div>
          </motion.div>
        </div>
        
        {/* Data Preview */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="lg:col-span-2 card overflow-hidden"
        >
          <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex items-center gap-3">
            <Table className="w-5 h-5 text-slate-500 dark:text-slate-400" />
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Data Preview</h2>
          </div>
          
          <div className="overflow-auto max-h-[600px]">
            <table className="w-full">
              <thead className="bg-slate-100 dark:bg-slate-800/50 sticky top-0">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Floor</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">#</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Extracted Text</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Qty</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Confidence</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-700/50">
                {preview?.data.map((item, index) => (
                  <tr key={index} className="hover:bg-slate-50 dark:hover:bg-slate-800/30">
                    <td className="px-4 py-3 text-sm text-slate-700 dark:text-slate-300">
                      {item.floor_name}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-400 font-mono">
                      {item.shape_index + 1}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-900 dark:text-white font-mono">
                      <div className="flex items-center gap-2">
                        {item.text || <span className="text-slate-500">—</span>}
                        {item.merged_count && item.merged_count > 1 && (
                          <span 
                            className="text-xs px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded font-semibold"
                            title={`${item.merged_count} detections merged`}
                          >
                            {item.merged_count} merged
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className="text-slate-900 dark:text-white font-mono">
                        {item.quantity || 1}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-slate-300 dark:bg-slate-700 rounded-full overflow-hidden">
                          <div 
                            className={clsx(
                              'h-full rounded-full',
                              item.confidence > 80 ? 'bg-emerald-500' :
                              item.confidence > 50 ? 'bg-amber-500' : 'bg-red-500'
                            )}
                            style={{ width: `${item.confidence}%` }}
                          />
                        </div>
                        <span className="text-slate-600 dark:text-slate-400 text-xs">{item.confidence}%</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className={clsx(
                        'px-2 py-0.5 rounded text-xs font-medium',
                        item.is_manual 
                          ? 'bg-sign-500/20 text-sign-400' 
                          : 'bg-blue-500/20 text-blue-400'
                      )}>
                        {item.is_manual ? 'Manual' : 'OCR'}
                      </span>
                    </td>
                  </tr>
                ))}
                
                {(!preview?.data || preview.data.length === 0) && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-500">
                      No data to export. Process floor plans first.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </motion.div>
        
        {/* Cross-Floor Summary */}
        {preview?.summary && preview.summary.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="lg:col-span-3 card overflow-hidden"
          >
            <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Table className="w-5 h-5 text-slate-500 dark:text-slate-400" />
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Cross-Floor Summary</h2>
              </div>
              <div className="text-sm text-slate-600 dark:text-slate-400">
                {preview.summary_stats?.unique_items || 0} unique items across {preview.summary_stats?.total_floors || 0} floors
              </div>
            </div>
            
            <div className="overflow-auto max-h-[500px]">
              <table className="w-full">
                <thead className="bg-slate-100 dark:bg-slate-800/50 sticky top-0">
                  <tr>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Text</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Total Qty</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Floors</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-700 dark:text-slate-300">Floor Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-700/50">
                  {preview.summary.map((item, index) => (
                    <tr key={index} className="hover:bg-slate-50 dark:hover:bg-slate-800/30">
                      <td className="px-4 py-3 text-sm text-slate-900 dark:text-white font-mono">
                        {item.text || <span className="text-slate-500">—</span>}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <span className="text-emerald-400 font-semibold">
                          {item.total_quantity}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <div className="flex items-center gap-1.5">
                          <span className="text-slate-700 dark:text-slate-300">{item.floor_count} floor{item.floor_count !== 1 ? 's' : ''}</span>
                          <span className="text-slate-500">•</span>
                          <span className="text-slate-600 dark:text-slate-400 font-mono text-xs">
                            {item.floors.join(', ')}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <div className="flex flex-wrap gap-2">
                          {item.floor_details.map((detail, idx) => (
                            <span
                              key={idx}
                              className="inline-flex items-center gap-1.5 px-2 py-1 bg-slate-200 dark:bg-slate-700/50 rounded text-xs"
                            >
                              <span className="text-slate-700 dark:text-slate-300">{detail.floor_name}</span>
                              <span className="text-slate-500">:</span>
                              <span className="text-emerald-500 dark:text-emerald-400 font-semibold">×{detail.quantity}</span>
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}
      </div>
    </div>
  )
}

