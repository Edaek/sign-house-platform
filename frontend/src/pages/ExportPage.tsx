import { useEffect, useState, useCallback, useRef } from 'react'
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
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Info
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import api, { 
  getTemplateMapping, 
  getTemplateData, 
  updateTemplateCell,
  TemplateData,
  TemplateDataResponse
} from '../lib/api'
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

// Editable cell component
function EditableCell({ 
  value, 
  row, 
  col, 
  isOcrCell, 
  onSave 
}: { 
  value: string | number
  row: number
  col: number
  isOcrCell: boolean
  onSave: (row: number, col: number, value: string | number) => Promise<void>
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(String(value))
  const [isSaving, setIsSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setEditValue(String(value))
  }, [value])

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  const handleSave = async () => {
    if (editValue === String(value)) {
      setIsEditing(false)
      return
    }

    setIsSaving(true)
    try {
      await onSave(row, col, editValue)
      setIsEditing(false)
    } catch {
      toast.error('Failed to save')
      setEditValue(String(value))
    }
    setIsSaving(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave()
    } else if (e.key === 'Escape') {
      setEditValue(String(value))
      setIsEditing(false)
    }
  }

  if (isEditing) {
    return (
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={handleSave}
          onKeyDown={handleKeyDown}
          disabled={isSaving}
          className="w-full px-2 py-1 text-sm bg-white dark:bg-slate-700 border-2 border-sign-500 rounded focus:outline-none"
        />
        {isSaving && (
          <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-sign-500" />
        )}
      </div>
    )
  }

  return (
    <div
      onClick={() => setIsEditing(true)}
      className={clsx(
        'px-2 py-1.5 cursor-pointer rounded transition-colors min-h-[32px] text-sm',
        isOcrCell 
          ? 'bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 font-semibold text-emerald-300' 
          : 'hover:bg-slate-700/50'
      )}
      title={isOcrCell ? 'OCR populated - Click to edit' : 'Click to edit'}
    >
      {value !== '' ? value : <span className="text-slate-500">—</span>}
    </div>
  )
}

// Template Preview Component - Full Width
function TemplatePreview({ 
  projectId, 
  hasTemplate,
  floorMapping
}: { 
  projectId: string
  hasTemplate: boolean
  floorMapping: Record<string, string>
}) {
  const [templateData, setTemplateData] = useState<TemplateData | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ocrCellSet, setOcrCellSet] = useState<Set<string>>(new Set())

  const fetchTemplateData = useCallback(async () => {
    if (!hasTemplate) return

    setIsLoading(true)
    setError(null)
    
    try {
      const response: TemplateDataResponse = await getTemplateData(projectId)
      setTemplateData(response.data)
      
      // Build OCR cell set for quick lookup
      const cellSet = new Set<string>()
      response.data.ocr_cells?.forEach(cell => {
        cellSet.add(`${cell.row}-${cell.col}`)
      })
      setOcrCellSet(cellSet)
    } catch (err) {
      console.error('Failed to fetch template data:', err)
      setError('Failed to load template data')
    }
    setIsLoading(false)
  }, [projectId, hasTemplate])

  useEffect(() => {
    fetchTemplateData()
  }, [fetchTemplateData, floorMapping])

  const handleCellSave = async (row: number, col: number, value: string | number) => {
    await updateTemplateCell(projectId, row, col, value)
    
    // Update local state
    if (templateData) {
      const newRows = templateData.rows.map(r => {
        if (r.row === row) {
          return {
            ...r,
            cells: r.cells.map(c => {
              if (c.col === col) {
                return { ...c, value }
              }
              return c
            })
          }
        }
        return r
      })
      setTemplateData({ ...templateData, rows: newRows })
    }
  }

  const isOcrCell = (row: number, col: number) => {
    return ocrCellSet.has(`${row}-${col}`)
  }

  if (!hasTemplate) {
    return null
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex items-center gap-3 text-slate-500">
          <Loader2 className="w-6 h-6 animate-spin" />
          <span>Loading template...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <p className="text-red-400">{error}</p>
        <button
          onClick={fetchTemplateData}
          className="flex items-center gap-2 text-sm text-sign-400 hover:text-sign-300"
        >
          <RefreshCw className="w-4 h-4" />
          Retry
        </button>
      </div>
    )
  }

  if (!templateData || templateData.rows.length === 0) {
    return (
      <div className="px-4 py-20 text-center text-slate-500">
        No data in template yet.
      </div>
    )
  }

  return (
    <div className="overflow-auto" style={{ height: 'calc(100vh - 280px)', minHeight: '500px' }}>
      <table className="w-full border-collapse text-sm">
        <thead className="bg-slate-800 sticky top-0 z-10">
          <tr>
            <th className="px-2 py-2 text-left text-xs font-medium text-slate-400 border-r border-slate-700 bg-slate-800 sticky left-0 z-20 w-12">
              #
            </th>
            {templateData.columns.map((col) => (
              <th 
                key={col.column}
                className="px-3 py-2 text-left text-xs font-medium text-slate-300 border-b border-slate-700 whitespace-nowrap min-w-[100px]"
              >
                <div className="flex flex-col gap-0.5">
                  <span className="text-slate-500 text-[10px]">{col.letter}</span>
                  <span className="truncate">{col.name || '—'}</span>
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {templateData.rows.map((row) => (
            <tr key={row.row} className="border-b border-slate-800 hover:bg-slate-800/50">
              <td className="px-2 py-1 text-xs text-slate-500 border-r border-slate-700 bg-slate-900/50 sticky left-0 font-mono">
                {row.row}
              </td>
              {row.cells.map((cell) => (
                <td 
                  key={`${row.row}-${cell.col}`}
                  className="px-1 py-0.5 text-slate-200"
                >
                  <EditableCell
                    value={cell.value}
                    row={row.row}
                    col={cell.col}
                    isOcrCell={isOcrCell(row.row, cell.col)}
                    onSave={handleCellSave}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// OCR Data Preview Component (fallback when no template)
function OcrDataPreview({ preview }: { preview: ExportPreview | null }) {
  if (!preview?.data || preview.data.length === 0) {
    return (
      <div className="px-4 py-20 text-center text-slate-500">
        No data to export. Process floor plans first.
      </div>
    )
  }

  return (
    <div className="overflow-auto" style={{ height: 'calc(100vh - 280px)', minHeight: '500px' }}>
      <table className="w-full">
        <thead className="bg-slate-800 sticky top-0">
          <tr>
            <th className="px-4 py-3 text-left text-sm font-medium text-slate-300">Floor</th>
            <th className="px-4 py-3 text-left text-sm font-medium text-slate-300">#</th>
            <th className="px-4 py-3 text-left text-sm font-medium text-slate-300">Extracted Text</th>
            <th className="px-4 py-3 text-left text-sm font-medium text-slate-300">Qty</th>
            <th className="px-4 py-3 text-left text-sm font-medium text-slate-300">Confidence</th>
            <th className="px-4 py-3 text-left text-sm font-medium text-slate-300">Source</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {preview.data.map((item, index) => (
            <tr key={index} className="hover:bg-slate-800/30">
              <td className="px-4 py-3 text-sm text-slate-300">
                {item.floor_name}
              </td>
              <td className="px-4 py-3 text-sm text-slate-400 font-mono">
                {item.shape_index + 1}
              </td>
              <td className="px-4 py-3 text-sm text-white font-mono">
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
                <span className="text-white font-mono">
                  {item.quantity || 1}
                </span>
              </td>
              <td className="px-4 py-3 text-sm">
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                    <div 
                      className={clsx(
                        'h-full rounded-full',
                        item.confidence > 80 ? 'bg-emerald-500' :
                        item.confidence > 50 ? 'bg-amber-500' : 'bg-red-500'
                      )}
                      style={{ width: `${item.confidence}%` }}
                    />
                  </div>
                  <span className="text-slate-400 text-xs">{item.confidence}%</span>
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
        </tbody>
      </table>
    </div>
  )
}

export default function ExportPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { currentProject, fetchProject } = useProjectStore()
  const [preview, setPreview] = useState<ExportPreview | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [exportFormat, setExportFormat] = useState<'excel' | 'csv'>('excel')
  const [includeMetadata, _setIncludeMetadata] = useState(true)
  const [floorMapping, setFloorMapping] = useState<Record<string, string>>({})
  const [showSummary, setShowSummary] = useState(false)
  
  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
      fetchPreview()
      loadTemplateMapping()
    }
  }, [projectId])
  
  const loadTemplateMapping = async () => {
    if (!projectId) return
    
    try {
      const response = await getTemplateMapping(projectId)
      if (response.floor_mapping) {
        setFloorMapping(response.floor_mapping)
      }
    } catch (error) {
      console.log('No template mapping found')
    }
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
  const hasTemplate = !!currentProject?.template
  
  if (isLoading && !preview) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }
  
  return (
    <div className="h-full flex flex-col">
      {/* Compact Header Bar */}
      <div className="flex-shrink-0 bg-slate-900/50 border-b border-slate-700 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link 
              to={`/project/${projectId}`}
              className="inline-flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
              Back
            </Link>
            
            <div className="h-6 w-px bg-slate-700" />
            
            <div>
              <h1 className="text-lg font-semibold text-white">Export Data</h1>
              <p className="text-xs text-slate-400">{currentProject?.name}</p>
            </div>
          </div>
          
          {/* Export Controls */}
          <div className="flex items-center gap-3">
            {/* Stats */}
            <div className="hidden md:flex items-center gap-4 text-xs text-slate-400 mr-4">
              <span>Items: <span className="text-white font-medium">{preview?.total_items || 0}</span></span>
              <span>Unique: <span className="text-emerald-400 font-medium">{preview?.summary_stats?.unique_items || 0}</span></span>
              <span>Floors: <span className="text-white font-medium">{currentProject?.floorplans?.length || 0}</span></span>
              {hasTemplate && (
                <span className="flex items-center gap-1 text-emerald-400">
                  <CheckCircle className="w-3 h-3" />
                  Template
                </span>
              )}
            </div>
            
            {/* Format Toggle */}
            <div className="flex rounded-lg overflow-hidden border border-slate-600">
              <button
                onClick={() => setExportFormat('excel')}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 text-sm transition-colors',
                  exportFormat === 'excel'
                    ? 'bg-sign-500 text-white'
                    : 'bg-slate-800 text-slate-400 hover:text-white'
                )}
              >
                <FileSpreadsheet className="w-4 h-4" />
                Excel
              </button>
              <button
                onClick={() => setExportFormat('csv')}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 text-sm transition-colors border-l border-slate-600',
                  exportFormat === 'csv'
                    ? 'bg-sign-500 text-white'
                    : 'bg-slate-800 text-slate-400 hover:text-white'
                )}
              >
                <FileText className="w-4 h-4" />
                CSV
              </button>
            </div>
            
            {/* Download Button */}
            <button
              onClick={handleExport}
              className="btn btn-primary flex items-center gap-2 px-4 py-1.5"
            >
              <Download className="w-4 h-4" />
              Download
            </button>
          </div>
        </div>
      </div>
      
      {/* Warning for incomplete floors */}
      {incompleteFoors.length > 0 && (
        <div className="flex-shrink-0 px-4 py-2 bg-amber-500/10 border-b border-amber-500/30 flex items-center gap-2 text-sm">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span className="text-amber-200">
            {incompleteFoors.length} floor(s) pending: {incompleteFoors.map(f => f.floor_name).join(', ')}
          </span>
        </div>
      )}
      
      {/* Info bar for auto-matching */}
      {hasTemplate && (
        <div className="flex-shrink-0 px-4 py-2 bg-blue-500/10 border-b border-blue-500/30 flex items-center gap-2 text-sm">
          <Info className="w-4 h-4 text-blue-400" />
          <span className="text-blue-200">
            OCR data auto-fills based on floor names matching column headers. 
            <span className="text-emerald-400 ml-1">Green cells</span> = OCR populated. Click any cell to edit.
          </span>
        </div>
      )}
      
      {/* Main Content - Full Width Template Preview */}
      <div className="flex-1 overflow-hidden">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="h-full card rounded-none border-x-0"
        >
          <div className="p-3 border-b border-slate-700 flex items-center justify-between bg-slate-800/50">
            <div className="flex items-center gap-3">
              <Table className="w-5 h-5 text-slate-400" />
              <h2 className="text-base font-semibold text-white">
                {hasTemplate ? 'Template Preview' : 'Data Preview'}
              </h2>
              {hasTemplate && (
                <span className="text-xs px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">
                  Editable
                </span>
              )}
            </div>
            
            {preview?.summary && preview.summary.length > 0 && (
              <button
                onClick={() => setShowSummary(!showSummary)}
                className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors"
              >
                {showSummary ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                Cross-Floor Summary
              </button>
            )}
          </div>
          
          {hasTemplate ? (
            <TemplatePreview 
              projectId={projectId!} 
              hasTemplate={hasTemplate}
              floorMapping={floorMapping}
            />
          ) : (
            <OcrDataPreview preview={preview} />
          )}
        </motion.div>
      </div>
      
      {/* Collapsible Cross-Floor Summary */}
      {showSummary && preview?.summary && preview.summary.length > 0 && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className="flex-shrink-0 border-t border-slate-700 bg-slate-900/80 max-h-64 overflow-auto"
        >
          <div className="p-3 border-b border-slate-700 flex items-center justify-between sticky top-0 bg-slate-900/95 backdrop-blur">
            <div className="flex items-center gap-2">
              <Table className="w-4 h-4 text-slate-400" />
              <span className="text-sm font-medium text-white">Cross-Floor Summary</span>
            </div>
            <span className="text-xs text-slate-400">
              {preview.summary_stats?.unique_items || 0} unique items across {preview.summary_stats?.total_floors || 0} floors
            </span>
          </div>
          
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50 sticky top-12">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Text</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Total</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Floor Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {preview.summary.map((item, index) => (
                <tr key={index} className="hover:bg-slate-800/30">
                  <td className="px-4 py-2 text-white font-mono">{item.text || '—'}</td>
                  <td className="px-4 py-2">
                    <span className="text-emerald-400 font-semibold">{item.total_quantity}</span>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap gap-1.5">
                      {item.floor_details.map((detail, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-slate-700/50 rounded text-xs"
                        >
                          <span className="text-slate-300">{detail.floor_name}</span>
                          <span className="text-emerald-400">×{detail.quantity}</span>
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </motion.div>
      )}
    </div>
  )
}
