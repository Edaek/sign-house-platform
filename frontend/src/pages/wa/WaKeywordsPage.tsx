import { useEffect, useState } from 'react'
import { useWaStore } from '../../store/waStore'
import toast from 'react-hot-toast'
import { Plus, Tag, Trash2 } from 'lucide-react'

export default function WaKeywordsPage() {
  const { keywords, fetchKeywords, createKeyword, deleteKeyword } = useWaStore()
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)

  useEffect(() => {
    fetchKeywords().then(() => setLoading(false))
  }, [fetchKeywords])

  async function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const synonymsRaw = form.get('synonyms') as string
    try {
      await createKeyword({
        term: form.get('term') as string,
        type: form.get('type') as string,
        synonyms: synonymsRaw.split(',').map((s) => s.trim()).filter(Boolean),
      })
      toast.success('Keyword created')
      setDialogOpen(false)
      fetchKeywords()
    } catch {
      toast.error('Failed to create keyword')
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteKeyword(id)
      toast.success('Keyword deleted')
      fetchKeywords()
    } catch {
      toast.error('Failed to delete')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-display font-bold text-slate-900 dark:text-white">Keywords</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">{keywords.length} keyword mappings</p>
        </div>
        <button onClick={() => setDialogOpen(true)} className="btn btn-primary text-sm px-3 py-1.5 flex items-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />New Keyword
        </button>
      </div>

      {/* Create dialog */}
      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-md mx-4">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Add Keyword</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Term</label>
                <input name="term" required className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Type</label>
                <select name="type" className="input w-full">
                  <option value="type_keyword">Type Keyword</option>
                  <option value="tag_keyword">Tag Keyword</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Synonyms (comma-separated)</label>
                <input name="synonyms" placeholder="syn1, syn2, syn3" className="input w-full" />
              </div>
              <div className="flex gap-2 pt-2">
                <button type="button" onClick={() => setDialogOpen(false)} className="btn btn-secondary flex-1">Cancel</button>
                <button type="submit" className="btn btn-primary flex-1">Create</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
        </div>
      ) : keywords.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Tag className="h-10 w-10 text-slate-300 dark:text-slate-600 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">No keywords yet</p>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-800/50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Term</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Type</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Synonyms</th>
                <th className="px-4 py-2.5 w-16"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {keywords.map((kw) => (
                <tr key={kw.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                  <td className="px-4 py-2.5 font-semibold text-slate-800 dark:text-slate-200">{kw.term}</td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                      kw.type === 'type_keyword'
                        ? 'bg-sign-500/15 text-sign-700 border-sign-500/25 dark:bg-sign-500/20 dark:text-sign-400 dark:border-sign-500/30'
                        : 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600'
                    }`}>
                      {kw.type === 'type_keyword' ? 'Type' : 'Tag'}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                    {kw.synonyms.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {kw.synonyms.map((s) => (
                          <span key={s} className="inline-flex items-center rounded-md bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 text-xs">{s}</span>
                        ))}
                      </div>
                    ) : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
                      onClick={() => handleDelete(kw.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
