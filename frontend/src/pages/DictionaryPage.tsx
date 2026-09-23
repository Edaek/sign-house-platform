import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { 
  Book, 
  Search, 
  Plus, 
  Edit3, 
  Trash2, 
  Check, 
  X, 
  Upload,
  Download,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Loader2
} from 'lucide-react'
import api from '../lib/api'
import PageContainer from '../components/PageContainer'
import toast from 'react-hot-toast'
import clsx from 'clsx'

interface DictionaryEntry {
  id: string
  english: string
  sign: string  // Sign name/code
  chinese: string[]  // Array of Chinese translations
  created_at: string | null
  updated_at: string | null
}

interface DictionaryStats {
  total: number
  with_chinese: number
  no_chinese: number
  total_translations: number
}

export default function DictionaryPage() {
  const [entries, setEntries] = useState<DictionaryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<DictionaryStats | null>(null)
  
  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editEnglish, setEditEnglish] = useState('')
  const [editSign, setEditSign] = useState('')
  const [editChinese, setEditChinese] = useState<string[]>([])
  const [newChineseInput, setNewChineseInput] = useState('')
  
  // New entry state
  const [showAddForm, setShowAddForm] = useState(false)
  const [newEnglish, setNewEnglish] = useState('')
  const [newSign, setNewSign] = useState('')
  const [newChineseList, setNewChineseList] = useState<string[]>([])
  const [newChineseInputField, setNewChineseInputField] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  
  // Bulk import state
  const [showBulkImport, setShowBulkImport] = useState(false)
  const [bulkData, setBulkData] = useState('')
  const [isImporting, setIsImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  
  const fetchEntries = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: '20',
      })
      if (search) params.append('search', search)
      
      const response = await api.get(`/dictionary?${params}`)
      setEntries(response.data.entries)
      setTotalPages(response.data.total_pages)
      setTotal(response.data.total)
    } catch (error) {
      console.error('Failed to fetch dictionary entries:', error)
      toast.error('Failed to load dictionary entries')
    } finally {
      setLoading(false)
    }
  }
  
  const fetchStats = async () => {
    try {
      const response = await api.get('/dictionary/stats')
      setStats(response.data)
    } catch (error) {
      console.error('Failed to fetch stats:', error)
    }
  }
  
  useEffect(() => {
    fetchEntries()
    fetchStats()
  }, [page])
  
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    fetchEntries()
  }
  
  // Add Chinese to new entry list
  const handleAddNewChinese = () => {
    const value = newChineseInputField.trim()
    if (value && !newChineseList.includes(value)) {
      setNewChineseList([...newChineseList, value])
      setNewChineseInputField('')
    }
  }
  
  // Remove Chinese from new entry list
  const handleRemoveNewChinese = (index: number) => {
    setNewChineseList(newChineseList.filter((_, i) => i !== index))
  }
  
  const handleAdd = async () => {
    if (!newEnglish.trim()) {
      toast.error('English word is required')
      return
    }
    
    setIsAdding(true)
    try {
      await api.post('/dictionary', {
        english: newEnglish,
        sign: newSign,
        chinese: newChineseList
      })
      toast.success('Entry added successfully')
      setNewEnglish('')
      setNewSign('')
      setNewChineseList([])
      setNewChineseInputField('')
      setShowAddForm(false)
      fetchEntries()
      fetchStats()
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to add entry')
    } finally {
      setIsAdding(false)
    }
  }
  
  const handleEdit = (entry: DictionaryEntry) => {
    setEditingId(entry.id)
    setEditEnglish(entry.english)
    setEditSign(entry.sign || '')
    setEditChinese([...entry.chinese])
    setNewChineseInput('')
  }
  
  // Add Chinese to edit list
  const handleAddEditChinese = () => {
    const value = newChineseInput.trim()
    if (value && !editChinese.includes(value)) {
      setEditChinese([...editChinese, value])
      setNewChineseInput('')
    }
  }
  
  // Remove Chinese from edit list
  const handleRemoveEditChinese = (index: number) => {
    setEditChinese(editChinese.filter((_, i) => i !== index))
  }
  
  const handleSaveEdit = async () => {
    if (!editingId) return
    
    if (!editEnglish.trim()) {
      toast.error('English word is required')
      return
    }
    
    try {
      await api.put(`/dictionary/${editingId}`, {
        english: editEnglish,
        sign: editSign,
        chinese: editChinese
      })
      toast.success('Entry updated successfully')
      setEditingId(null)
      setEditEnglish('')
      setEditSign('')
      setEditChinese([])
      setNewChineseInput('')
      fetchEntries()
      fetchStats()
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to update entry')
    }
  }
  
  const handleCancelEdit = () => {
    setEditingId(null)
    setEditEnglish('')
    setEditSign('')
    setEditChinese([])
    setNewChineseInput('')
  }
  
  const handleDelete = async (id: string) => {
    if (!window.confirm('Are you sure you want to delete this entry?')) {
      return
    }
    
    try {
      await api.delete(`/dictionary/${id}`)
      toast.success('Entry deleted successfully')
      fetchEntries()
      fetchStats()
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to delete entry')
    }
  }
  
  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    
    // Validate file type
    if (!file.name.endsWith('.csv')) {
      toast.error('Please upload a CSV file')
      return
    }
    
    setIsImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      
      const response = await api.post('/dictionary/import-csv', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })
      
      const message = `Created ${response.data.created}, updated ${response.data.updated}, skipped ${response.data.skipped}`
      toast.success(message)
      setShowBulkImport(false)
      fetchEntries()
      fetchStats()
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to import CSV file')
    } finally {
      setIsImporting(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }
  
  const handleBulkImport = async () => {
    if (!bulkData.trim()) {
      toast.error('Please enter data to import')
      return
    }
    
    setIsImporting(true)
    try {
      // Parse bulk data - supports two formats:
      // 1. English,Sign,Chinese (with Chinese as semicolon-separated: 出口;退出)
      // 2. English,Sign,Chinese1,Chinese2,... (comma-separated columns)
      const lines = bulkData.trim().split('\n')
      const entries = lines.map(line => {
        const parts = line.split(',').map(p => p.trim())
        if (parts.length === 0 || !parts[0]) return null
        
        const english = parts[0] || ''
        const sign = parts[1] || ''
        
        // Get Chinese translations
        let chinese: string[] = []
        if (parts.length > 2) {
          const thirdCol = parts[2] || ''
          // Check if third column contains semicolons (export format)
          if (thirdCol.includes(';')) {
            chinese = thirdCol.split(';').map(c => c.trim()).filter(c => c)
          } else {
            // Multiple column format - all columns after sign are Chinese
            chinese = parts.slice(2).filter(p => p)
          }
        }
        
        return { english, sign, chinese }
      }).filter((e): e is { english: string; sign: string; chinese: string[] } => e !== null && !!e.english)
      
      if (entries.length === 0) {
        toast.error('No valid entries found')
        setIsImporting(false)
        return
      }
      
      const response = await api.post('/dictionary/bulk', { entries })
      const message = `Created ${response.data.created}, updated ${response.data.updated}, skipped ${response.data.skipped}`
      toast.success(message)
      setBulkData('')
      setShowBulkImport(false)
      fetchEntries()
      fetchStats()
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to import entries')
    } finally {
      setIsImporting(false)
    }
  }
  
  const handleExport = async () => {
    try {
      const response = await api.get('/dictionary/export', {
        responseType: 'blob'
      })
      const blob = new Blob([response.data], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'dictionary-export.csv'
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Dictionary exported successfully')
    } catch (error) {
      toast.error('Failed to export dictionary')
    }
  }
  
  // Render Chinese tags
  const renderChineseTags = (chineseList: string[], isEditing: boolean = false, onRemove?: (index: number) => void) => {
    if (!chineseList || chineseList.length === 0) {
      return <span className="text-slate-400 dark:text-slate-500 italic">(no translations)</span>
    }
    
    return (
      <div className="flex flex-wrap gap-1.5">
        {chineseList.map((cn, idx) => (
          <span 
            key={idx}
            className={clsx(
              'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-sm',
              'bg-sign-100 text-sign-800 dark:bg-sign-900/40 dark:text-sign-200'
            )}
          >
            {cn}
            {isEditing && onRemove && (
              <button
                onClick={() => onRemove(idx)}
                className="ml-0.5 hover:text-red-600 dark:hover:text-red-400"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </span>
        ))}
      </div>
    )
  }
  
  return (
    <PageContainer>
      <div className="page-header">
        <div className="flex items-center gap-3 mb-2">
          <Book className="h-8 w-8 text-sign-500" />
          <h1 className="page-title">
            Dictionary
          </h1>
        </div>
        <p className="page-subtitle">
          English-Sign-Chinese dictionary with multiple Chinese translations per word
        </p>
      </div>
      
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
            <div className="text-2xl font-bold text-slate-900 dark:text-white">{stats.total}</div>
            <div className="text-sm text-slate-500 dark:text-slate-400">English Words</div>
          </div>
          <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
            <div className="text-2xl font-bold text-sign-600 dark:text-sign-400">{stats.total_translations}</div>
            <div className="text-sm text-slate-500 dark:text-slate-400">Chinese Translations</div>
          </div>
          <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
            <div className="text-2xl font-bold text-sign-600 dark:text-sign-400">{stats.with_chinese}</div>
            <div className="text-sm text-slate-500 dark:text-slate-400">With Translations</div>
          </div>
          <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
            <div className="text-2xl font-bold text-slate-500 dark:text-slate-400">{stats.no_chinese}</div>
            <div className="text-sm text-slate-500 dark:text-slate-400">Pending Translations</div>
          </div>
        </div>
      )}
      
      {/* Toolbar */}
      <div className="bg-white dark:bg-slate-800 rounded-lg shadow-sm p-4 mb-6 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col md:flex-row gap-4">
          {/* Search */}
          <form onSubmit={handleSearch} className="flex-1 flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-slate-400" />
              <input
                type="text"
                placeholder="Search English or Chinese..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="input pl-10"
              />
            </div>
            <button type="submit" className="btn btn-primary">
              Search
            </button>
          </form>
          
          <div className="flex gap-2">
            <button
              onClick={() => setShowAddForm(true)}
              className="btn btn-primary"
            >
              <Plus className="w-4 h-4" />
              <span className="hidden sm:inline">Add Entry</span>
            </button>
            <button
              onClick={() => setShowBulkImport(true)}
              className="btn btn-secondary"
            >
              <Upload className="w-4 h-4" />
              <span className="hidden sm:inline">Import</span>
            </button>
            <button
              onClick={handleExport}
              className="btn btn-secondary"
            >
              <Download className="w-4 h-4" />
              <span className="hidden sm:inline">Export</span>
            </button>
            <button
              onClick={() => fetchEntries()}
              className="btn btn-secondary p-2"
            >
              <RefreshCw className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
      
      {/* Add Entry Form */}
      {showAddForm && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-4 mb-6"
        >
          <h3 className="font-semibold text-slate-900 dark:text-white mb-3">Add New Entry</h3>
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">English Word</label>
                <input
                  type="text"
                  placeholder="Enter English word"
                  value={newEnglish}
                  onChange={(e) => setNewEnglish(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Sign Name/Code</label>
                <input
                  type="text"
                  placeholder="Enter sign name (optional)"
                  value={newSign}
                  onChange={(e) => setNewSign(e.target.value)}
                  className="input"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Chinese Translations</label>
              <div className="flex gap-2 mb-2">
                <input
                  type="text"
                  placeholder="Add Chinese translation"
                  value={newChineseInputField}
                  onChange={(e) => setNewChineseInputField(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleAddNewChinese()
                    }
                  }}
                  className="input flex-1"
                />
                <button
                  onClick={handleAddNewChinese}
                  type="button"
                  className="btn btn-primary btn-sm"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
              {newChineseList.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {newChineseList.map((cn, idx) => (
                    <span 
                      key={idx}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-sm bg-sign-100 text-sign-800 dark:bg-sign-900/40 dark:text-sign-200"
                    >
                      {cn}
                      <button
                        onClick={() => handleRemoveNewChinese(idx)}
                        className="ml-0.5 hover:text-red-600 dark:hover:text-red-400"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex gap-2 pt-2">
              <button
                onClick={handleAdd}
                disabled={isAdding}
                className="btn btn-primary"
              >
                {isAdding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                Save Entry
              </button>
              <button
                onClick={() => {
                  setShowAddForm(false)
                  setNewEnglish('')
                  setNewSign('')
                  setNewChineseList([])
                  setNewChineseInputField('')
                }}
                className="btn btn-secondary"
              >
                <X className="w-4 h-4" />
                Cancel
              </button>
            </div>
          </div>
        </motion.div>
      )}
      
      {/* Bulk Import Form */}
      {showBulkImport && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-4 mb-6"
        >
          <h3 className="font-semibold text-slate-900 dark:text-white mb-3">Import Dictionary</h3>
          
          <div className="mb-4 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg border-2 border-dashed border-slate-300 dark:border-slate-600">
            <div className="text-center">
              <Upload className="w-8 h-8 mx-auto mb-2 text-sign-500" />
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-2">
                Upload a CSV file (compatible with export format)
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={handleFileUpload}
                disabled={isImporting}
                className="hidden"
                id="csv-upload"
              />
              <label
                htmlFor="csv-upload"
                className={clsx(
                  "btn btn-primary cursor-pointer",
                  isImporting && "opacity-50 cursor-not-allowed"
                )}
              >
                {isImporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                Choose CSV File
              </label>
            </div>
          </div>
          
          <div className="flex items-center gap-3 mb-4">
            <div className="flex-1 border-t border-slate-200 dark:border-slate-700"></div>
            <span className="text-sm text-slate-500 dark:text-slate-400">or paste data</span>
            <div className="flex-1 border-t border-slate-200 dark:border-slate-700"></div>
          </div>
          
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-2">
            Format: <code className="bg-slate-100 dark:bg-slate-700 px-1 rounded">English,Sign,Chinese1;Chinese2</code>
          </p>
          <textarea
            value={bulkData}
            onChange={(e) => setBulkData(e.target.value)}
            placeholder="Exit,EXIT-001,translation A;translation B&#10;Fire,FIRE-001,translation A;translation B"
            rows={4}
            className="input font-mono text-sm"
          />
          <div className="flex gap-2 mt-3">
            <button
              onClick={handleBulkImport}
              disabled={isImporting || !bulkData.trim()}
              className="btn btn-primary"
            >
              {isImporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              Import Text
            </button>
            <button
              onClick={() => {
                setShowBulkImport(false)
                setBulkData('')
              }}
              className="btn btn-secondary"
            >
              <X className="w-4 h-4" />
              Cancel
            </button>
          </div>
        </motion.div>
      )}
      
      {/* Entries Table */}
      <div className="bg-white dark:bg-slate-800 rounded-lg shadow-sm overflow-hidden border border-slate-200 dark:border-slate-700">
        {loading ? (
          <div className="p-8 text-center">
            <Loader2 className="w-8 h-8 animate-spin text-sign-500 mx-auto mb-2" />
            <span className="text-slate-500 dark:text-slate-400">Loading entries...</span>
          </div>
        ) : entries.length === 0 ? (
          <div className="p-8 text-center text-slate-500 dark:text-slate-400">
            <Book className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No dictionary entries found</p>
            {search && <p className="text-sm mt-1">Try a different search term</p>}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-50 dark:bg-slate-700/50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider w-1/5">
                      English
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider w-1/5">
                      Sign
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      Chinese translations
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider w-24">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                  {entries.map((entry) => (
                    <tr key={entry.id} className="hover:bg-slate-50 dark:hover:bg-slate-700/30">
                      <td className="px-6 py-4">
                        {editingId === entry.id ? (
                          <input
                            type="text"
                            value={editEnglish}
                            onChange={(e) => setEditEnglish(e.target.value)}
                            className="w-full px-2 py-1 border border-slate-300 dark:border-slate-600 rounded focus:ring-2 focus:ring-sign-500 dark:bg-slate-700 dark:text-white"
                            autoFocus
                          />
                        ) : (
                          <span className="text-slate-900 dark:text-white font-medium">
                            {entry.english}
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        {editingId === entry.id ? (
                          <input
                            type="text"
                            value={editSign}
                            onChange={(e) => setEditSign(e.target.value)}
                            placeholder="Sign name"
                            className="w-full px-2 py-1 border border-slate-300 dark:border-slate-600 rounded focus:ring-2 focus:ring-sign-500 dark:bg-slate-700 dark:text-white"
                          />
                        ) : (
                          <span className="text-sign-600 dark:text-sign-400">
                            {entry.sign || <span className="text-slate-400 dark:text-slate-500 italic">—</span>}
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        {editingId === entry.id ? (
                          <div className="space-y-2">
                            <div className="flex gap-2">
                              <input
                                type="text"
                                placeholder="Add translation"
                                value={newChineseInput}
                                onChange={(e) => setNewChineseInput(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault()
                                    handleAddEditChinese()
                                  }
                                }}
                                className="flex-1 px-2 py-1 border border-slate-300 dark:border-slate-600 rounded focus:ring-2 focus:ring-sign-500 dark:bg-slate-700 dark:text-white text-sm"
                              />
                              <button
                                onClick={handleAddEditChinese}
                                className="btn btn-primary btn-sm px-2 py-1"
                              >
                                <Plus className="w-3 h-3" />
                              </button>
                            </div>
                            {renderChineseTags(editChinese, true, handleRemoveEditChinese)}
                          </div>
                        ) : (
                          renderChineseTags(entry.chinese)
                        )}
                      </td>
                      <td className="px-6 py-4 text-right">
                        {editingId === entry.id ? (
                          <div className="flex justify-end gap-2">
                            <button
                              onClick={handleSaveEdit}
                              className="p-1.5 text-sign-600 hover:bg-sign-100 dark:text-sign-400 dark:hover:bg-sign-900/30 rounded transition-colors"
                              title="Save"
                            >
                              <Check className="w-4 h-4" />
                            </button>
                            <button
                              onClick={handleCancelEdit}
                              className="p-1.5 text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-700 rounded transition-colors"
                              title="Cancel"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          </div>
                        ) : (
                          <div className="flex justify-end gap-2">
                            <button
                              onClick={() => handleEdit(entry)}
                              className="p-1.5 text-sign-600 hover:bg-sign-100 dark:text-sign-400 dark:hover:bg-sign-900/30 rounded transition-colors"
                              title="Edit"
                            >
                              <Edit3 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDelete(entry.id)}
                              className="p-1.5 text-red-600 hover:bg-red-100 dark:text-red-400 dark:hover:bg-red-900/30 rounded transition-colors"
                              title="Delete"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            {/* Pagination */}
            <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
              <div className="text-sm text-slate-600 dark:text-slate-400">
                Showing {entries.length} of {total} entries
              </div>
              
              {totalPages > 1 && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="btn btn-secondary p-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-sm text-slate-600 dark:text-slate-400 min-w-[100px] text-center">
                    Page {page} of {totalPages}
                  </span>
                  <button
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="btn btn-secondary p-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </PageContainer>
  )
}
