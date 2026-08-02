import { useState } from 'react'
import { useWaStore, type WaRecord } from '../../store/waStore'
import WaRecordTable from '../../components/wa/RecordTable'
import { Search as SearchIcon } from 'lucide-react'

export default function WaSearchPage() {
  const { searchRecords } = useWaStore()
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [results, setResults] = useState<WaRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setSearched(true)
    try {
      const params: Record<string, string> = {}
      if (query) params.q = query
      if (status) params.status = status
      const data = await searchRecords(params)
      setResults(data)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold text-slate-900 dark:text-white">Search</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">Search across all WA records</p>
      </div>

      <form onSubmit={handleSearch} className="flex gap-3">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Reference number, phone, message text..."
            className="input pl-9 w-full"
          />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="input px-3 text-sm w-auto">
          <option value="">All statuses</option>
          <option value="incomplete">Incomplete</option>
          <option value="followup">Follow-up</option>
          <option value="awaiting_review">Awaiting Review</option>
          <option value="completed">Completed</option>
          <option value="voided">Voided</option>
        </select>
        <button type="submit" disabled={loading} className="btn btn-primary text-sm px-4 py-2 flex items-center gap-1.5">
          <SearchIcon className="h-3.5 w-3.5" />
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {searched && (
        <div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
            {results.length} result{results.length !== 1 ? 's' : ''} found
          </p>
          <WaRecordTable records={results} />
        </div>
      )}

      {!searched && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <SearchIcon className="h-10 w-10 text-slate-300 dark:text-slate-600 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">Enter a search query to find records</p>
        </div>
      )}
    </div>
  )
}
