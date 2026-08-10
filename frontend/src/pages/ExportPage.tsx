import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { 
  ChevronLeft,
  FileSpreadsheet,
  AlertTriangle,
  Table,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Search,
  BookPlus,
  Check,
  Image as ImageIcon,
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import { 
  getSignTableData,
  updateSignTableCell,
  updateSignTableFloorCount,
  searchDictionary,
  addToDictionary,
  SignTable,
  SignTableCellUpdateResponse,
  DictionarySearchResult
} from '../lib/api'
import api from '../lib/api'
import toast from 'react-hot-toast'
import clsx from 'clsx'

// Editable cell component for Sign and Sign No columns
function EditableCell({ 
  value, 
  rowNumber, 
  field,
  onSave,
  className = ''
}: { 
  value: string
  rowNumber: number
  field: 'sign' | 'sign_no'
  onSave: (rowNumber: number, field: 'sign' | 'english' | 'chinese' | 'sign_no', value: string) => Promise<SignTableCellUpdateResponse>
  className?: string
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
      className={clsx(
        "px-2 py-1.5 cursor-pointer rounded transition-colors min-h-[32px] text-sm hover:bg-slate-700/50",
        className
      )}
      title="Click to edit"
    >
      {value !== '' ? value : <span className="text-slate-500">—</span>}
    </div>
  )
}

// Editable cell component for floor counts (numbers)
function EditableFloorCountCell({ 
  value, 
  rowNumber, 
  floorplanId,
  onSave 
}: { 
  value: number
  rowNumber: number
  floorplanId: string
  onSave: (rowNumber: number, floorplanId: string, value: number) => Promise<SignTableCellUpdateResponse>
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(String(value || ''))
  const [isSaving, setIsSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setEditValue(String(value || ''))
  }, [value])

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  const handleSave = async () => {
    const numValue = parseInt(editValue) || 0
    if (numValue === value) {
      setIsEditing(false)
      return
    }

    setIsSaving(true)
    try {
      await onSave(rowNumber, floorplanId, numValue)
      setIsEditing(false)
    } catch {
      toast.error('Failed to save')
      setEditValue(String(value || ''))
    }
    setIsSaving(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave()
    } else if (e.key === 'Escape') {
      setEditValue(String(value || ''))
      setIsEditing(false)
    }
  }

  if (isEditing) {
    return (
      <div className="relative">
        <input
          ref={inputRef}
          type="number"
          min="0"
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={handleSave}
          onKeyDown={handleKeyDown}
          disabled={isSaving}
          className="w-full px-2 py-1 text-sm text-center bg-white dark:bg-slate-700 border-2 border-sign-500 rounded focus:outline-none"
        />
        {isSaving && (
          <Loader2 className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-sign-500" />
        )}
      </div>
    )
  }

  return (
    <div
      onClick={() => setIsEditing(true)}
      className="px-2 py-1.5 cursor-pointer rounded transition-colors min-h-[32px] text-sm text-center hover:bg-sign-500/10"
      title="Click to edit"
    >
      {value > 0 ? (
        <span className="text-sign-400 font-medium">{value}</span>
      ) : (
        <span className="text-slate-600">—</span>
      )}
    </div>
  )
}

// English cell with instant search autocomplete
function EnglishAutocompleteCell({ 
  value, 
  rowNumber,
  onSave,
  onSignUpdate,
  onChineseUpdate,
  onChineseOptions
}: { 
  value: string
  rowNumber: number
  onSave: (rowNumber: number, field: 'sign' | 'english' | 'chinese', value: string) => Promise<SignTableCellUpdateResponse>
  onSignUpdate: (rowNumber: number, sign: string) => void
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
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
      // Save the English value - backend will auto-fill sign and chinese
      await onSave(rowNumber, 'english', suggestion.english)
      
      // If sign was available from suggestion, update local state immediately
      if (suggestion.sign) {
        onSignUpdate(rowNumber, suggestion.sign)
      }
      
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
            className="w-full px-2 py-1 pr-8 text-sm bg-white dark:bg-slate-700 border-2 border-sign-500 rounded focus:outline-none"
          />
          {isSearching ? (
            <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-sign-500" />
          ) : (
            <Search className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-sign-400" />
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
                onMouseDown={(e) => {
                  // Prevent blur from firing before click
                  e.preventDefault()
                }}
                onClick={() => handleSelectSuggestion(suggestion)}
                className={clsx(
                  'px-3 py-2 cursor-pointer text-sm border-b border-slate-700 last:border-0',
                  idx === selectedIndex ? 'bg-sign-600/30' : 'hover:bg-slate-700'
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-white">{suggestion.english}</span>
                  {suggestion.sign && (
                    <span className="text-xs px-1.5 py-0.5 bg-sign-500/20 text-sign-300 rounded">
                      {suggestion.sign}
                    </span>
                  )}
                </div>
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
      className="px-2 py-1.5 cursor-pointer rounded transition-colors min-h-[32px] text-sm hover:bg-sign-500/10 border border-transparent hover:border-sign-500/30"
      title="Click to edit with dictionary search"
    >
      {value !== '' ? (
        <span className="text-sign-300">{value}</span>
      ) : (
        <span className="text-slate-500 flex items-center gap-1">
          <Search className="w-3 h-3" />
          Search...
        </span>
      )}
    </div>
  )
}

// Editable Chinese cell with save to dictionary option
function ChineseEditableCell({ 
  value, 
  rowNumber,
  englishValue,
  knownTranslations,
  onSave,
  onSaveToDictionary
}: { 
  value: string
  rowNumber: number
  englishValue: string
  knownTranslations: string[]  // Known Chinese translations for this English word
  onSave: (rowNumber: number, field: 'sign' | 'english' | 'chinese', value: string) => Promise<SignTableCellUpdateResponse>
  onSaveToDictionary: (rowNumber: number, english: string, chinese: string) => Promise<void>
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(value)
  const [isSaving, setIsSaving] = useState(false)
  const [isSavingToDict, setIsSavingToDict] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
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

  const handleSaveToDictionary = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!englishValue || !value) return
    
    setIsSavingToDict(true)
    try {
      await onSaveToDictionary(rowNumber, englishValue, value)
      setJustSaved(true)
      setTimeout(() => setJustSaved(false), 2000)
    } catch {
      // Error handled in parent
    }
    setIsSavingToDict(false)
  }

  // Show save to dictionary icon when both English and Chinese have values and this Chinese translation is not in dictionary
  const isTranslationInDictionary = knownTranslations.includes(value)
  const canSaveToDictionary = englishValue && value && !isTranslationInDictionary && !justSaved

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
          className="w-full px-2 py-1 text-sm bg-white dark:bg-slate-700 border-2 border-sign-400 rounded focus:outline-none"
        />
        {isSaving && (
          <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-sign-400" />
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1">
      <div
        onClick={() => setIsEditing(true)}
        className="flex-1 px-2 py-1.5 cursor-pointer rounded transition-colors min-h-[32px] text-sm hover:bg-sign-400/10 border border-transparent hover:border-sign-400/30"
        title="Click to edit"
      >
        {value !== '' ? (
          <span className="text-sign-200">{value}</span>
        ) : (
          <span className="text-slate-500">—</span>
        )}
      </div>
      
      {/* Save to dictionary button */}
      {canSaveToDictionary && (
        <button
          onClick={handleSaveToDictionary}
          disabled={isSavingToDict}
          className="p-1 rounded hover:bg-sign-500/20 text-sign-400 hover:text-sign-300 transition-colors"
          title="Save to dictionary"
        >
          {isSavingToDict ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <BookPlus className="w-4 h-4" />
          )}
        </button>
      )}
      
      {/* Just saved indicator */}
      {justSaved && (
        <span className="text-sign-400">
          <Check className="w-4 h-4" />
        </span>
      )}
    </div>
  )
}

// Chinese selection dropdown when multiple translations available
function ChineseSelectCell({
  value,
  options,
  rowNumber,
  englishValue,
  onSave,
  onSaveToDictionary
}: {
  value: string
  options: string[]
  rowNumber: number
  englishValue: string
  onSave: (rowNumber: number, field: 'sign' | 'english' | 'chinese', value: string) => Promise<SignTableCellUpdateResponse>
  onSaveToDictionary: (rowNumber: number, english: string, chinese: string) => Promise<void>
}) {
  const [isSaving, setIsSaving] = useState(false)
  const [isSavingToDict, setIsSavingToDict] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [isAddingNew, setIsAddingNew] = useState(false)
  const [newValue, setNewValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isAddingNew && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isAddingNew])

  const handleSelect = async (selected: string) => {
    if (selected === '__add_new__') {
      setIsAddingNew(true)
      setNewValue('')
      return
    }
    
    if (selected === value) return // No change
    
    setIsSaving(true)
    try {
      await onSave(rowNumber, 'chinese', selected)
    } catch {
      toast.error('Failed to save')
    }
    setIsSaving(false)
  }

  const handleSaveNewValue = async () => {
    if (!newValue.trim()) {
      setIsAddingNew(false)
      return
    }
    
    setIsSaving(true)
    try {
      await onSave(rowNumber, 'chinese', newValue.trim())
      setIsAddingNew(false)
      setNewValue('')
    } catch {
      toast.error('Failed to save')
    }
    setIsSaving(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSaveNewValue()
    } else if (e.key === 'Escape') {
      setIsAddingNew(false)
      setNewValue('')
    }
  }

  const handleSaveToDictionary = async () => {
    if (!englishValue || !value) return
    
    setIsSavingToDict(true)
    try {
      await onSaveToDictionary(rowNumber, englishValue, value)
      setJustSaved(true)
      setTimeout(() => setJustSaved(false), 2000)
    } catch {
      // Error handled in parent
    }
    setIsSavingToDict(false)
  }

  // Check if current value is NOT in the options (meaning it was manually entered)
  const isManualEntry = value && !options.includes(value)

  if (isAddingNew) {
    return (
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          onBlur={handleSaveNewValue}
          onKeyDown={handleKeyDown}
          disabled={isSaving}
          placeholder="Enter new translation..."
          className="w-full px-2 py-1 text-sm bg-white dark:bg-slate-700 border-2 border-sign-400 rounded focus:outline-none"
        />
        {isSaving && (
          <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-sign-400" />
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1">
      <div className="relative flex-1">
        <select
          value={value || ''}
          onChange={(e) => handleSelect(e.target.value)}
          disabled={isSaving}
          className="w-full px-2 py-1.5 text-sm bg-sign-900/20 border border-sign-400/40 rounded text-sign-200 cursor-pointer appearance-none focus:outline-none hover:bg-sign-900/30"
        >
          {!value && <option value="" disabled>Select translation...</option>}
          {/* Show current value if it's not in options (manual entry) */}
          {isManualEntry && (
            <option value={value} className="bg-slate-800 text-white">
              {value}
            </option>
          )}
          {options.map((opt, idx) => (
            <option key={idx} value={opt} className="bg-slate-800 text-white">
              {opt}
            </option>
          ))}
          {/* Add new option */}
          <option value="__add_new__" className="bg-slate-700 text-sign-400">
            ＋ Add new translation...
          </option>
        </select>
        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-sign-300 pointer-events-none" />
        {isSaving && (
          <Loader2 className="absolute right-7 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-sign-400" />
        )}
      </div>
      
      {/* Save to dictionary button for manual entries */}
      {isManualEntry && !justSaved && (
        <button
          onClick={handleSaveToDictionary}
          disabled={isSavingToDict}
          className="p-1 rounded hover:bg-sign-500/20 text-sign-400 hover:text-sign-300 transition-colors"
          title="Save to dictionary"
        >
          {isSavingToDict ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <BookPlus className="w-4 h-4" />
          )}
        </button>
      )}
      
      {/* Just saved indicator */}
      {justSaved && (
        <span className="text-sign-400">
          <Check className="w-4 h-4" />
        </span>
      )}
    </div>
  )
}

function FloorThumbnail({ floorplanId, floorName, signNo, entryId, onClick }: {
  floorplanId: string
  floorName: string
  signNo: string
  entryId?: string
  onClick: (entryId?: string) => void
}) {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let revoked = false
    const params = entryId
      ? `entry_id=${encodeURIComponent(entryId)}`
      : `sign_no=${encodeURIComponent(signNo)}`
    const url = `/processing/image/${floorplanId}/shape-crop?${params}`
    api.get(url, { responseType: 'blob' })
      .then(res => {
        if (revoked) return
        setSrc(URL.createObjectURL(res.data))
      })
      .catch(() => {})
    return () => { revoked = true; if (src) URL.revokeObjectURL(src) }
  }, [floorplanId, signNo, entryId])

  return (
    <button
      onClick={() => onClick(entryId)}
      className="flex flex-col items-center w-full p-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded hover:border-sign-400 dark:hover:border-sign-500 hover:shadow-md transition-all group cursor-pointer"
    >
      <div className="w-full h-14 bg-slate-100 dark:bg-slate-700 rounded overflow-hidden">
        {src ? (
          <img src={src} alt={floorName} className="w-full h-full object-contain" />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <ImageIcon className="w-4 h-4 text-slate-400" />
          </div>
        )}
      </div>
    </button>
  )
}

interface ShapeEntry {
  id: string
  x: number
  y: number
  width: number
  height: number
  quantity: number
}

const THUMB_COLLAPSE_LIMIT = 3

function FloorThumbnailCell({ floorplanId, floorName, signNo, count, projectId }: {
  floorplanId: string
  floorName: string
  signNo: string
  count: number
  projectId: string
}) {
  const navigate = useNavigate()
  const [entries, setEntries] = useState<ShapeEntry[]>([])
  const [loaded, setLoaded] = useState(false)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.get(`/processing/image/${floorplanId}/shape-entries?sign_no=${encodeURIComponent(signNo)}`)
      .then(res => {
        if (cancelled) return
        setEntries(res.data.entries || [])
        setLoaded(true)
      })
      .catch(() => setLoaded(true))
    return () => { cancelled = true }
  }, [floorplanId, signNo])

  const handleClick = (entryId?: string) => {
    const qs = entryId ? `?highlight=${entryId}` : ''
    navigate(`/project/${projectId}/floor/${floorplanId}${qs}`)
  }

  if (!loaded) {
    return (
      <div className="flex items-center justify-center h-14">
        <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
      </div>
    )
  }

  if (entries.length === 0) {
    return (
      <FloorThumbnail
        floorplanId={floorplanId}
        floorName={floorName}
        signNo={signNo}
        onClick={handleClick}
      />
    )
  }

  const visible = expanded ? entries : entries.slice(0, THUMB_COLLAPSE_LIMIT)
  const hiddenCount = entries.length - THUMB_COLLAPSE_LIMIT

  return (
    <div className="flex flex-col gap-1">
      {visible.map(entry => (
        <FloorThumbnail
          key={entry.id}
          floorplanId={floorplanId}
          floorName={floorName}
          signNo={signNo}
          entryId={entry.id}
          onClick={handleClick}
        />
      ))}
      {entries.length > THUMB_COLLAPSE_LIMIT && (
        <button
          onClick={() => setExpanded(prev => !prev)}
          className="text-[9px] text-sign-500 dark:text-sign-400 hover:underline cursor-pointer py-0.5"
        >
          {expanded ? 'Show less' : `+${hiddenCount} more`}
        </button>
      )}
      <div className="text-[9px] text-center text-slate-500 dark:text-slate-400">Qty: {count}</div>
    </div>
  )
}

// Sign Table Preview Component
function SignTablePreview({ 
  projectId,
  onColumnsReady,
}: { 
  projectId: string
  onColumnsReady?: (columns: string[], names: string[]) => void
}) {
  const [signTable, setSignTable] = useState<SignTable | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Track rows with available Chinese translations (for dropdown)
  const [chineseOptions, setChineseOptions] = useState<Record<number, string[]>>({})
  // Track which rows we've already fetched options for
  const [fetchedRows, setFetchedRows] = useState<Set<number>>(new Set())
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())

  const toggleRowExpand = (rowNumber: number) => {
    setExpandedRows(prev => {
      const next = new Set(prev)
      if (next.has(rowNumber)) {
        next.delete(rowNumber)
      } else {
        next.add(rowNumber)
      }
      return next
    })
  }

  const fetchSignTableData = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    
    try {
      const response = await getSignTableData(projectId)
      setSignTable(response.sign_table)
      onColumnsReady?.(response.sign_table.floorplan_columns, response.sign_table.floorplan_column_names ?? response.sign_table.floorplan_columns)
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
          if (response.data.found && response.data.chinese && response.data.chinese.length > 0) {
            // Store all known translations so we can check if current value is in dictionary
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

  const handleCellSave = async (rowNumber: number, field: 'sign' | 'english' | 'chinese' | 'sign_no', value: string) => {
    const result = await updateSignTableCell(projectId, rowNumber, field, value)
    
    // Update local state using functional update to avoid stale closure
    setSignTable(prev => {
      if (!prev) return prev
      const newRows = prev.rows.map(row => {
        if (row.row_number === rowNumber) {
          const updated = { ...row, [field]: value }
          // If Sign was auto-filled, update it too
          if (result.sign_auto_filled) {
            updated.sign = result.sign_auto_filled
          }
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
    
    // Show notification if dictionary was updated
    if (result.dictionary_updated) {
      toast.success('Dictionary updated with Sign')
    }
    
    return result
  }

  const handleFloorCountSave = async (rowNumber: number, floorplanId: string, value: number) => {
    const result = await updateSignTableFloorCount(projectId, rowNumber, floorplanId, value)
    
    setSignTable(prev => {
      if (!prev) return prev
      const newRows = prev.rows.map(row => {
        if (row.row_number === rowNumber) {
          const updatedFloorCounts = { ...row.floor_counts }
          if (value > 0) {
            updatedFloorCounts[floorplanId] = value
          } else {
            delete updatedFloorCounts[floorplanId]
          }
          return { ...row, floor_counts: updatedFloorCounts }
        }
        return row
      })
      return { ...prev, rows: newRows }
    })
    
    return result
  }

  const handleSignUpdate = (rowNumber: number, sign: string) => {
    // Update Sign in local state when auto-filled from English selection
    setSignTable(prev => {
      if (!prev) return prev
      const newRows = prev.rows.map(row => {
        if (row.row_number === rowNumber) {
          return { ...row, sign }
        }
        return row
      })
      return { ...prev, rows: newRows }
    })
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
      if (response.data.found && response.data.chinese && response.data.chinese.length > 0) {
        // Store all known translations (even if just one) so we can check if current value is in dictionary
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

  const handleSaveToDictionary = async (rowNumber: number, english: string, chinese: string) => {
    try {
      const result = await addToDictionary(english, chinese)
      
      if (result.action === 'created') {
        toast.success(`Added "${english}" to dictionary`)
      } else if (result.action === 'added') {
        toast.success(`Added translation to "${english}"`)
      } else {
        toast.success('Translation already in dictionary')
      }
      
      // Update Chinese options with all translations from the dictionary
      if (result.entry.chinese && result.entry.chinese.length > 0) {
        setChineseOptions(prev => ({ ...prev, [rowNumber]: result.entry.chinese }))
      }
    } catch (err: any) {
      toast.error(err.response?.data?.error || 'Failed to save to dictionary')
      throw err
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

  const floorColumns = signTable.floorplan_columns
  const floorColumnNames = signTable.floorplan_column_names ?? floorColumns

  return (
    <div className="overflow-auto" style={{ height: 'calc(100vh - 280px)', minHeight: '400px' }}>
      <table className="w-full border-collapse text-sm">
        <thead className="bg-slate-800 sticky top-0 z-10">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 border-b border-slate-700 w-12">
              #
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-300 border-b border-slate-700 min-w-[100px]">
              Sign No.
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-300 border-b border-slate-700 min-w-[120px]">
              Sign
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-sign-300 border-b border-slate-700 min-w-[150px] bg-sign-900/20">
              English
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-sign-200 border-b border-slate-700 min-w-[120px] bg-sign-900/20">
              Chinese
            </th>
            
            {floorColumnNames.map((name, idx) => (
              <th 
                key={floorColumns[idx]}
                className="px-3 py-2 text-center text-xs font-medium text-sign-300 border-b border-slate-700 min-w-[80px] bg-sign-900/10"
              >
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {signTable.rows.flatMap((row) => {
            const isExpanded = expandedRows.has(row.row_number)
            const hasFloors = floorColumns.some(id => (row.floor_counts[id] || 0) > 0)

            return [
              <tr key={row.row_number} className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                {/* Row number — click to expand */}
                <td className="px-0 py-0.5">
                  <button
                    onClick={() => hasFloors && toggleRowExpand(row.row_number)}
                    className={clsx(
                      'flex items-center gap-1 w-full px-2 py-1 text-xs font-mono rounded transition-colors',
                      hasFloors
                        ? 'text-sign-600 dark:text-sign-400 hover:bg-sign-50 dark:hover:bg-sign-900/20 cursor-pointer'
                        : 'text-slate-400 dark:text-slate-500 cursor-default'
                    )}
                    disabled={!hasFloors}
                  >
                    {hasFloors && (
                      isExpanded
                        ? <ChevronDown className="w-3 h-3 flex-shrink-0" />
                        : <ChevronRight className="w-3 h-3 flex-shrink-0" />
                    )}
                    {row.row_number}
                  </button>
                </td>
                
                {/* Sign No. (editable) */}
                <td className="px-1 py-0.5 bg-white/50 dark:bg-slate-800/30">
                  <EditableCell
                    value={row.sign_no}
                    rowNumber={row.row_number}
                    field="sign_no"
                    onSave={handleCellSave}
                    className="font-mono text-slate-900 dark:text-white"
                  />
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
                <td className="px-1 py-0.5 bg-sign-50/50 dark:bg-sign-900/5">
                  <EnglishAutocompleteCell
                    value={row.english}
                    rowNumber={row.row_number}
                    onSave={handleCellSave}
                    onSignUpdate={handleSignUpdate}
                    onChineseUpdate={handleChineseUpdate}
                    onChineseOptions={handleChineseOptions}
                  />
                </td>
                
                {/* Chinese (editable, with dropdown for multiple options) */}
                <td className="px-1 py-0.5 bg-sign-50/50 dark:bg-sign-900/5">
                  {chineseOptions[row.row_number] && chineseOptions[row.row_number].length > 1 ? (
                    <ChineseSelectCell
                      value={row.chinese}
                      options={chineseOptions[row.row_number]}
                      rowNumber={row.row_number}
                      englishValue={row.english}
                      onSave={handleCellSave}
                      onSaveToDictionary={handleSaveToDictionary}
                    />
                  ) : (
                    <ChineseEditableCell
                      value={row.chinese}
                      rowNumber={row.row_number}
                      englishValue={row.english}
                      knownTranslations={chineseOptions[row.row_number] || []}
                      onSave={handleCellSave}
                      onSaveToDictionary={handleSaveToDictionary}
                    />
                  )}
                </td>
                
                {floorColumns.map((fpId) => {
                  const count = row.floor_counts[fpId] || 0
                  return (
                    <td 
                      key={`${row.row_number}-${fpId}`}
                      className="px-1 py-0.5 bg-sign-50/30 dark:bg-sign-900/5"
                    >
                      <EditableFloorCountCell
                        value={count}
                        rowNumber={row.row_number}
                        floorplanId={fpId}
                        onSave={handleFloorCountSave}
                      />
                    </td>
                  )
                })}
              </tr>,

              ...(isExpanded ? [
                <tr key={`${row.row_number}-expand`} className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                  <td /><td /><td /><td /><td />
                  {floorColumns.map((fpId, idx) => {
                    const count = row.floor_counts[fpId] || 0
                    if (count > 0) {
                      const displayName = floorColumnNames[idx] ?? fpId
                      return (
                        <td key={`${row.row_number}-thumb-${idx}`} className="px-1 py-1 align-top">
                          <FloorThumbnailCell
                            floorplanId={fpId}
                            floorName={displayName}
                            signNo={row.sign_no}
                            count={count}
                            projectId={projectId}
                          />
                        </td>
                      )
                    }
                    return <td key={`${row.row_number}-thumb-${idx}`} />
                  })}
                </tr>
              ] : [])
            ]
          })}
        </tbody>
      </table>

    </div>
  )
}

export default function ExportPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { currentProject, fetchProject } = useProjectStore()
  const [isLoading, setIsLoading] = useState(true)
  const [allFloorColumns, setAllFloorColumns] = useState<string[]>([])
  const [allFloorColumnNames, setAllFloorColumnNames] = useState<string[]>([])
  const [showExportModal, setShowExportModal] = useState(false)
  const [exportSelectedIdxs, setExportSelectedIdxs] = useState<Set<number>>(new Set())
  const [exportSelectedFixed, setExportSelectedFixed] = useState<Set<string>>(new Set())

  const FIXED_COLUMNS = ['Sign No.', 'Sign', 'English', 'Chinese'] as const
  
  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
      setIsLoading(false)
    }
  }, [projectId])

  const openExportModal = () => {
    setExportSelectedIdxs(new Set(allFloorColumns.map((_, i) => i)))
    setExportSelectedFixed(new Set(FIXED_COLUMNS))
    setShowExportModal(true)
  }
  
  const handleExport = async (selectedFloorIdxs?: number[], selectedFixed?: Set<string>) => {
    if (!projectId) return
    setShowExportModal(false)
    
    const floorCols = selectedFloorIdxs
      ? selectedFloorIdxs.map(i => allFloorColumns[i])
      : allFloorColumns
    const fixedCols = selectedFixed
      ? FIXED_COLUMNS.filter(c => selectedFixed.has(c))
      : [...FIXED_COLUMNS]

    try {
      const response = await api.post(`/export/excel/${projectId}`, 
        { selected_columns: floorCols, selected_fixed_columns: fixedCols },
        { responseType: 'blob' }
      )
      
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `${currentProject?.name || 'export'}.xlsx`)
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
            <button 
              onClick={() => navigate(-1)}
              className="inline-flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
              Back
            </button>
            
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
            
            {/* Download Button */}
            <button
              onClick={openExportModal}
              className="btn btn-primary flex items-center gap-2 px-4 py-1.5"
            >
              <FileSpreadsheet className="w-4 h-4" />
              Download Excel
            </button>
          </div>
        </div>
      </div>
      
      {/* Warning for incomplete floors */}
      {incompleteFoors.length > 0 && (
        <div className="flex-shrink-0 px-4 py-2 bg-sign-400/10 border-b border-sign-400/30 flex items-center gap-2 text-sm">
          <AlertTriangle className="w-4 h-4 text-sign-400" />
          <span className="text-sign-200">
            {incompleteFoors.length} floor(s) pending: {incompleteFoors.map(f => f.floor_name).join(', ')}
          </span>
        </div>
      )}
      
      {/* Info bar */}
      <div className="flex-shrink-0 px-4 py-2 bg-sign-500/10 border-b border-sign-500/30 flex items-center gap-2 text-sm">
        <Search className="w-4 h-4 text-sign-400" />
        <span className="text-sign-700 dark:text-sign-300">
          Click on <span className="text-sign-300 font-medium">English</span> cells to search the dictionary. 
          <span className="text-slate-300 ml-1">Sign</span> and <span className="text-sign-200">Chinese</span> auto-fill from matches.
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
              <span className="text-xs px-2 py-0.5 bg-sign-500/20 text-sign-400 rounded">
                Auto-generated
              </span>
            </div>
          </div>
          
          {projectId && (
            <SignTablePreview
              projectId={projectId}
              onColumnsReady={(cols, names) => { setAllFloorColumns(cols); setAllFloorColumnNames(names) }}
            />
          )}
        </motion.div>
      </div>

      {/* Export Column Selection Modal */}
      {showExportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 dark:bg-black/60" onClick={() => setShowExportModal(false)}>
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-2xl w-full max-w-md mx-4 max-h-[80vh] flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-700">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Select Columns to Export</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {exportSelectedFixed.size + exportSelectedIdxs.size} / {FIXED_COLUMNS.length + allFloorColumns.length} selected
              </p>
            </div>

            <div className="px-5 py-3 border-b border-slate-200/80 dark:border-slate-700/50">
              <label className="flex items-center gap-3 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={
                    exportSelectedFixed.size === FIXED_COLUMNS.length &&
                    allFloorColumns.length > 0 &&
                    exportSelectedIdxs.size === allFloorColumns.length
                  }
                  onChange={() => {
                    const allChecked = exportSelectedFixed.size === FIXED_COLUMNS.length && exportSelectedIdxs.size === allFloorColumns.length
                    if (allChecked) {
                      setExportSelectedFixed(new Set())
                      setExportSelectedIdxs(new Set())
                    } else {
                      setExportSelectedFixed(new Set(FIXED_COLUMNS))
                      setExportSelectedIdxs(new Set(allFloorColumns.map((_, i) => i)))
                    }
                  }}
                  className="accent-sign-500 w-4 h-4 cursor-pointer"
                />
                <span className="text-sm font-medium text-slate-900 dark:text-white group-hover:text-sign-600 dark:group-hover:text-sign-300 transition-colors">
                  Select All
                </span>
              </label>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-2">
              <div className="text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-semibold mb-1 mt-1">Fixed Columns</div>
              {FIXED_COLUMNS.map((col) => (
                <label
                  key={col}
                  className="flex items-center gap-3 py-2 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700/30 -mx-2 px-2 rounded transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={exportSelectedFixed.has(col)}
                    onChange={() => {
                      setExportSelectedFixed(prev => {
                        const next = new Set(prev)
                        if (next.has(col)) next.delete(col); else next.add(col)
                        return next
                      })
                    }}
                    className="accent-sign-500 w-4 h-4 cursor-pointer"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-200">{col}</span>
                </label>
              ))}

              <div className="text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-semibold mb-1 mt-3">Floor Columns</div>
              {allFloorColumns.map((_id, idx) => (
                <label
                  key={idx}
                  className="flex items-center gap-3 py-2 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700/30 -mx-2 px-2 rounded transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={exportSelectedIdxs.has(idx)}
                    onChange={() => {
                      setExportSelectedIdxs(prev => {
                        const next = new Set(prev)
                        if (next.has(idx)) next.delete(idx); else next.add(idx)
                        return next
                      })
                    }}
                    className="accent-sign-500 w-4 h-4 cursor-pointer"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-200">{allFloorColumnNames[idx] ?? _id}</span>
                </label>
              ))}
            </div>

            <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-700 flex items-center justify-end gap-3">
              <button
                onClick={() => setShowExportModal(false)}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-800 dark:text-slate-300 dark:hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleExport(Array.from(exportSelectedIdxs), exportSelectedFixed)}
                disabled={exportSelectedFixed.size + exportSelectedIdxs.size === 0}
                className="btn btn-primary flex items-center gap-2 px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <FileSpreadsheet className="w-4 h-4" />
                Export ({exportSelectedFixed.size + exportSelectedIdxs.size})
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  )
}
