import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { 
  ChevronLeft,
  Download,
  FileSpreadsheet,
  FileText,
  AlertTriangle,
  Table,
  Loader2,
  RefreshCw,
  ChevronDown,
  Search,
  X
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import { 
  getSignTableData,
  updateSignTableCell,
  searchDictionary,
  SignTable,
  SignRow,
  DictionarySearchResult
} from '../lib/api'
import api from '../lib/api'
import toast from 'react-hot-toast'
import clsx from 'clsx'

// Editable cell component for Sign column
function EditableCell({ 
  value, 
  rowNumber, 
  field,
  onSave 
}: { 
  value: string
  rowNumber: number
  field: 'sign'
  onSave: (rowNumber: number, field: 'sign' | 'english' | 'chinese', value: string) => Promise<void>
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(value)
  const [isSaving, setIsSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setEditValue(value)
  }, [value])

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  const handleSave = async () => {
    if (editValue === value) {
      setIsEditing(false)
      return
    }

    setIsSaving(true)
    try {
      await onSave(rowNumber, field, editValue)
      setIsEditing(false)
    } catch {
      toast.error('Failed to save')
      setEditValue(value)
    }
    setIsSaving(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave()
    } else if (e.key === 'Escape') {
      setEditValue(value)
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
      className="px-2 py-1.5 cursor-pointer rounded transition-colors min-h-[32px] text-sm hover:bg-slate-700/50"
      title="Click to edit"
    >
      {value !== '' ? value : <span className="text-slate-500">—</span>}
    </div>
  )
}

// English cell with instant search autocomplete
function EnglishAutocompleteCell({ 
  value, 
  rowNumber,
  onSave,
  onChineseUpdate,
  onChineseOptions
}: { 
  value: string
  rowNumber: number
  onSave: (rowNumber: number, field: 'sign' | 'english' | 'chinese', value: string) => Promise<void>
  onChineseUpdate: (rowNumber: number, chinese: string) => void
  onChineseOptions: (rowNumber: number, options: string[]) => void
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(value)
  const [isSaving, setIsSaving] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [suggestions, setSuggestions] = useState<DictionarySearchResult[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    setEditValue(value)
  }, [value])

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isEditing])

  // Search dictionary with debounce
  const searchWithDebounce = useCallback((query: string) => {
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
    }

    if (!query.trim()) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }

    searchTimeoutRef.current = setTimeout(async () => {
      setIsSearching(true)
      try {
        const response = await searchDictionary(query, 8)
        setSuggestions(response.results)
        setShowSuggestions(response.results.length > 0)
        setSelectedIndex(-1)
      } catch {
        setSuggestions([])
      }
      setIsSearching(false)
    }, 300)
  }, [])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value
    setEditValue(newValue)
    searchWithDebounce(newValue)
  }

  const handleSelectSuggestion = async (suggestion: DictionarySearchResult) => {
    setEditValue(suggestion.english)
    setShowSuggestions(false)
    setSuggestions([])
    
    setIsSaving(true)
    try {
      // Save the English value
      await onSave(rowNumber, 'english', suggestion.english)
      
      // Auto-fill and save Chinese from the suggestion
      if (suggestion.chinese && suggestion.chinese.length > 0) {
        if (suggestion.chinese.length === 1) {
          // Only one translation - auto-fill it
          const chineseValue = suggestion.chinese[0]
          await onSave(rowNumber, 'chinese', chineseValue)
          onChineseUpdate(rowNumber, chineseValue)
        } else {
          // Multiple translations - pass them to parent for selection
          onChineseOptions(rowNumber, suggestion.chinese)
        }
      }
      setIsEditing(false)
    } catch {
      toast.error('Failed to save')
    }
    setIsSaving(false)
  }

  const handleSave = async () => {
    setShowSuggestions(false)
    if (editValue === value) {
      setIsEditing(false)
      return
    }

    setIsSaving(true)
    try {
      await onSave(rowNumber, 'english', editValue)
      setIsEditing(false)
    } catch {
      toast.error('Failed to save')
      setEditValue(value)
    }
    setIsSaving(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showSuggestions && suggestions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex(prev => Math.min(prev + 1, suggestions.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex(prev => Math.max(prev - 1, -1))
      } else if (e.key === 'Enter' && selectedIndex >= 0) {
        e.preventDefault()
        handleSelectSuggestion(suggestions[selectedIndex])
      } else if (e.key === 'Escape') {
        setShowSuggestions(false)
        setSelectedIndex(-1)
      }
    } else {
      if (e.key === 'Enter') {
        handleSave()
      } else if (e.key === 'Escape') {
        setEditValue(value)
        setIsEditing(false)
      }
    }
  }

  const handleBlur = (e: React.FocusEvent) => {
    // Don't close if clicking on dropdown
    if (dropdownRef.current?.contains(e.relatedTarget as Node)) {
      return
    }
    
    setTimeout(() => {
      setShowSuggestions(false)
      if (!isSaving && editValue !== value) {
        handleSave()
      } else if (!isSaving) {
        setIsEditing(false)
      }
    }, 150)
  }

  if (isEditing) {
    return (
      <div className="relative">
        <div className="relative">
          <input
            ref={inputRef}
            type="text"
            value={editValue}
            onChange={handleInputChange}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            disabled={isSaving}
            placeholder="Type to search..."
            className="w-full px-2 py-1 pr-8 text-sm bg-white dark:bg-slate-700 border-2 border-blue-500 rounded focus:outline-none"
          />
          {isSearching ? (
            <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-blue-500" />
          ) : (
            <Search className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-blue-400" />
          )}
        </div>
        
        {/* Suggestions dropdown */}
        {showSuggestions && suggestions.length > 0 && (
          <div 
            ref={dropdownRef}
            className="absolute z-50 w-full mt-1 bg-slate-800 border border-slate-600 rounded-lg shadow-xl max-h-48 overflow-auto"
          >
            {suggestions.map((suggestion, idx) => (
              <div
                key={suggestion.english}
                onClick={() => handleSelectSuggestion(suggestion)}
                className={clsx(
                  'px-3 py-2 cursor-pointer text-sm border-b border-slate-700 last:border-0',
                  idx === selectedIndex ? 'bg-blue-600/30' : 'hover:bg-slate-700'
                )}
              >
                <div className="font-medium text-white">{suggestion.english}</div>
                {suggestion.chinese.length > 0 && (
                  <div className="text-xs text-slate-400 mt-0.5">
                    {suggestion.chinese.join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      onClick={() => setIsEditing(true)}
      className="px-2 py-1.5 cursor-pointer rounded transition-colors min-h-[32px] text-sm hover:bg-blue-500/10 border border-transparent hover:border-blue-500/30"
      title="Click to edit with dictionary search"
    >
      {value !== '' ? (
        <span className="text-blue-300">{value}</span>
      ) : (
        <span className="text-slate-500 flex items-center gap-1">
          <Search className="w-3 h-3" />
          Search...
        </span>
      )}
    </div>
  )
}

// Editable Chinese cell
function ChineseEditableCell({ 
  value, 
  rowNumber,
  onSave 
}: { 
  value: string
  rowNumber: number
  onSave: (rowNumber: number, field: 'sign' | 'english' | 'chinese', value: string) => Promise<void>
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(value)
  const [isSaving, setIsSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setEditValue(value)
  }, [value])

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  const handleSave = async () => {
    if (editValue === value) {
      setIsEditing(false)
      return
    }

    setIsSaving(true)
    try {
      await onSave(rowNumber, 'chinese', editValue)
      setIsEditing(false)
    } catch {
      toast.error('Failed to save')
      setEditValue(value)
    }
    setIsSaving(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave()
    } else if (e.key === 'Escape') {
      setEditValue(value)
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
          className="w-full px-2 py-1 text-sm bg-white dark:bg-slate-700 border-2 border-purple-500 rounded focus:outline-none"
        />
        {isSaving && (
          <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-purple-500" />
        )}
      </div>
    )
  }

  return (
    <div
      onClick={() => setIsEditing(true)}
      className="px-2 py-1.5 cursor-pointer rounded transition-colors min-h-[32px] text-sm hover:bg-purple-500/10 border border-transparent hover:border-purple-500/30"
      title="Click to edit"
    >
      {value !== '' ? (
        <span className="text-purple-300">{value}</span>
      ) : (
        <span className="text-slate-500">—</span>
      )}
    </div>
  )
}

// Chinese selection dropdown when multiple translations available
function ChineseSelectCell({
  value,
  options,
  rowNumber,
  onSave
}: {
  value: string
  options: string[]
  rowNumber: number
  onSave: (rowNumber: number, field: 'sign' | 'english' | 'chinese', value: string) => Promise<void>
}) {
  const [isSaving, setIsSaving] = useState(false)

  const handleSelect = async (selected: string) => {
    if (selected === value) return // No change
    
    setIsSaving(true)
    try {
      await onSave(rowNumber, 'chinese', selected)
    } catch {
      toast.error('Failed to save')
    }
    setIsSaving(false)
  }

  return (
    <div className="relative">
      <select
        value={value || ''}
        onChange={(e) => handleSelect(e.target.value)}
        disabled={isSaving}
        className="w-full px-2 py-1.5 text-sm bg-purple-900/20 border border-purple-500/40 rounded text-purple-200 cursor-pointer appearance-none focus:outline-none hover:bg-purple-900/30"
      >
        {!value && <option value="" disabled>Select translation...</option>}
        {options.map((opt, idx) => (
          <option key={idx} value={opt} className="bg-slate-800 text-white">
            {opt}
          </option>
        ))}
      </select>
      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-purple-400 pointer-events-none" />
      {isSaving && (
        <Loader2 className="absolute right-7 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-purple-500" />
      )}
    </div>
  )
}

// Sign Table Preview Component
function SignTablePreview({ 
  projectId 
}: { 
  projectId: string
}) {
  const [signTable, setSignTable] = useState<SignTable | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Track rows with available Chinese translations (for dropdown)
  const [chineseOptions, setChineseOptions] = useState<Record<number, string[]>>({})
  // Track which rows we've already fetched options for
  const [fetchedRows, setFetchedRows] = useState<Set<number>>(new Set())

  const fetchSignTableData = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    
    try {
      const response = await getSignTableData(projectId)
      setSignTable(response.sign_table)
      // Reset fetched rows when table is reloaded
      setFetchedRows(new Set())
      setChineseOptions({})
    } catch (err) {
      console.error('Failed to fetch sign table data:', err)
      setError('Failed to load sign table data')
    }
    setIsLoading(false)
  }, [projectId])

  useEffect(() => {
    fetchSignTableData()
  }, [fetchSignTableData])

  // Fetch Chinese translations for rows that have English values
  useEffect(() => {
    if (!signTable) return

    const fetchChineseOptions = async () => {
      const newOptions: Record<number, string[]> = { ...chineseOptions }
      const newFetched = new Set(fetchedRows)
      
      for (const row of signTable.rows) {
        // Skip if already fetched or no English value
        if (fetchedRows.has(row.row_number) || !row.english) continue
        
        try {
          // Look up all Chinese translations for this English word
          const response = await api.get(`/dictionary/lookup?english=${encodeURIComponent(row.english)}`)
          if (response.data.found && response.data.chinese && response.data.chinese.length > 1) {
            newOptions[row.row_number] = response.data.chinese
          }
          newFetched.add(row.row_number)
        } catch {
          // Ignore lookup errors
          newFetched.add(row.row_number)
        }
      }
      
      if (newFetched.size > fetchedRows.size) {
        setFetchedRows(newFetched)
        setChineseOptions(newOptions)
      }
    }

    fetchChineseOptions()
  }, [signTable?.rows])

  const handleCellSave = async (rowNumber: number, field: 'sign' | 'english' | 'chinese', value: string) => {
    const result = await updateSignTableCell(projectId, rowNumber, field, value)
    
    // Update local state using functional update to avoid stale closure
    setSignTable(prev => {
      if (!prev) return prev
      const newRows = prev.rows.map(row => {
        if (row.row_number === rowNumber) {
          const updated = { ...row, [field]: value }
          // If Chinese was auto-filled, update it too
          if (result.chinese_auto_filled) {
            updated.chinese = result.chinese_auto_filled
          }
          return updated
        }
        return row
      })
      return { ...prev, rows: newRows }
    })

    // If English was updated, refetch Chinese options
    if (field === 'english') {
      refetchChineseOptions(rowNumber, value)
    }
  }

  const handleChineseUpdate = (rowNumber: number, chinese: string) => {
    // Update Chinese in local state when auto-filled from English selection
    setSignTable(prev => {
      if (!prev) return prev
      const newRows = prev.rows.map(row => {
        if (row.row_number === rowNumber) {
          return { ...row, chinese }
        }
        return row
      })
      return { ...prev, rows: newRows }
    })
  }

  const handleChineseOptions = (rowNumber: number, options: string[]) => {
    // Store options for this row to show selection dropdown
    setChineseOptions(prev => ({ ...prev, [rowNumber]: options }))
    // Mark as fetched
    setFetchedRows(prev => new Set([...prev, rowNumber]))
  }

  const clearChineseOptions = (rowNumber: number) => {
    // Don't clear - keep showing dropdown for multiple options
    // This function is now a no-op but kept for interface compatibility
  }

  // Refetch options when English value changes
  const refetchChineseOptions = async (rowNumber: number, english: string) => {
    if (!english) {
      setChineseOptions(prev => {
        const updated = { ...prev }
        delete updated[rowNumber]
        return updated
      })
      return
    }

    try {
      const response = await api.get(`/dictionary/lookup?english=${encodeURIComponent(english)}`)
      if (response.data.found && response.data.chinese && response.data.chinese.length > 1) {
        setChineseOptions(prev => ({ ...prev, [rowNumber]: response.data.chinese }))
      } else {
        setChineseOptions(prev => {
          const updated = { ...prev }
          delete updated[rowNumber]
          return updated
        })
      }
    } catch {
      // Ignore errors
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex items-center gap-3 text-slate-500">
          <Loader2 className="w-6 h-6 animate-spin" />
          <span>Loading sign table...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <p className="text-red-400">{error}</p>
        <button
          onClick={fetchSignTableData}
          className="flex items-center gap-2 text-sm text-sign-400 hover:text-sign-300"
        >
          <RefreshCw className="w-4 h-4" />
          Retry
        </button>
      </div>
    )
  }

  if (!signTable || signTable.rows.length === 0) {
    return (
      <div className="px-4 py-20 text-center text-slate-500">
        <Table className="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p>No sign data yet. Process floor plans to generate the sign table.</p>
      </div>
    )
  }

  // Fixed columns + dynamic floorplan columns
  const fixedColumns = ['#', 'Sign No.', 'Sign', 'English', 'Chinese']
  const floorColumns = signTable.floorplan_columns

  return (
    <div className="overflow-auto" style={{ height: 'calc(100vh - 280px)', minHeight: '400px' }}>
      <table className="w-full border-collapse text-sm">
        <thead className="bg-slate-800 sticky top-0 z-10">
          <tr>
            {/* Fixed columns */}
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 border-b border-slate-700 w-12">
              #
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-300 border-b border-slate-700 min-w-[100px]">
              Sign No.
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-300 border-b border-slate-700 min-w-[120px]">
              Sign
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-blue-300 border-b border-slate-700 min-w-[150px] bg-blue-900/20">
              English
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-purple-300 border-b border-slate-700 min-w-[120px] bg-purple-900/20">
              Chinese
            </th>
            
            {/* Dynamic floorplan columns */}
            {floorColumns.map((floorName) => (
              <th 
                key={floorName}
                className="px-3 py-2 text-center text-xs font-medium text-emerald-300 border-b border-slate-700 min-w-[80px] bg-emerald-900/10"
              >
                {floorName}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {signTable.rows.map((row) => (
            <tr key={row.row_number} className="border-b border-slate-800 hover:bg-slate-800/50">
              {/* Row number */}
              <td className="px-3 py-1 text-xs text-slate-500 font-mono">
                {row.row_number}
              </td>
              
              {/* Sign No. (extracted, read-only) */}
              <td className="px-3 py-1 text-white font-mono bg-slate-800/30">
                {row.sign_no}
              </td>
              
              {/* Sign (editable) */}
              <td className="px-1 py-0.5">
                <EditableCell
                  value={row.sign}
                  rowNumber={row.row_number}
                  field="sign"
                  onSave={handleCellSave}
                />
              </td>
              
              {/* English (editable with autocomplete) */}
              <td className="px-1 py-0.5 bg-blue-900/5">
                <EnglishAutocompleteCell
                  value={row.english}
                  rowNumber={row.row_number}
                  onSave={handleCellSave}
                  onChineseUpdate={handleChineseUpdate}
                  onChineseOptions={handleChineseOptions}
                />
              </td>
              
              {/* Chinese (editable, with dropdown for multiple options) */}
              <td className="px-1 py-0.5 bg-purple-900/5">
                {chineseOptions[row.row_number] && chineseOptions[row.row_number].length > 1 ? (
                  // Show dropdown when multiple translations available
                  <ChineseSelectCell
                    value={row.chinese}
                    options={chineseOptions[row.row_number]}
                    rowNumber={row.row_number}
                    onSave={handleCellSave}
                  />
                ) : (
                  <ChineseEditableCell
                    value={row.chinese}
                    rowNumber={row.row_number}
                    onSave={handleCellSave}
                  />
                )}
              </td>
              
              {/* Floor count columns */}
              {floorColumns.map((floorName) => {
                const count = row.floor_counts[floorName] || 0
                return (
                  <td 
                    key={`${row.row_number}-${floorName}`}
                    className="px-3 py-1.5 text-center bg-emerald-900/5"
                  >
                    {count > 0 ? (
                      <span className="text-emerald-400 font-medium">{count}</span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                )
              })}
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
  const [isLoading, setIsLoading] = useState(true)
  const [exportFormat, setExportFormat] = useState<'excel' | 'csv'>('excel')
  
  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
      setIsLoading(false)
    }
  }, [projectId])
  
  const handleExport = async () => {
    if (!projectId) return
    
    try {
      const endpoint = exportFormat === 'excel' 
        ? `/export/excel/${projectId}`
        : `/export/csv/${projectId}`
      
      const response = await api.post(endpoint, 
        { include_metadata: true },
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
  const totalItems = currentProject?.floorplans?.reduce((sum, fp) => sum + (fp.data_count || 0), 0) || 0
  
  if (isLoading && !currentProject) {
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
              <span>Items: <span className="text-white font-medium">{totalItems}</span></span>
              <span>Floors: <span className="text-white font-medium">{currentProject?.floorplans?.length || 0}</span></span>
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
      
      {/* Info bar */}
      <div className="flex-shrink-0 px-4 py-2 bg-blue-500/10 border-b border-blue-500/30 flex items-center gap-2 text-sm">
        <Search className="w-4 h-4 text-blue-400" />
        <span className="text-blue-200">
          Click on <span className="text-blue-300 font-medium">English</span> cells to search the dictionary. 
          <span className="text-purple-300 ml-1">Chinese</span> auto-fills from matches.
        </span>
      </div>
      
      {/* Main Content - Sign Table */}
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
                Sign Table
              </h2>
              <span className="text-xs px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">
                Auto-generated
              </span>
            </div>
          </div>
          
          {projectId && <SignTablePreview projectId={projectId} />}
        </motion.div>
      </div>
    </div>
  )
}
