import { useEffect, useState } from 'react'
import { useWaStore } from '../../store/waStore'
import WaStatusBadge from '../../components/wa/StatusBadge'
import toast from 'react-hot-toast'
import { Plus, BookText } from 'lucide-react'

export default function WaTemplatesPage() {
  const { templates, fetchTemplates, createTemplate } = useWaStore()
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [fields, setFields] = useState<Array<{ name: string; type: string; required: boolean }>>([
    { name: '', type: 'text', required: false },
  ])

  useEffect(() => {
    fetchTemplates().then(() => setLoading(false))
  }, [fetchTemplates])

  async function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const validFields = fields.filter((f) => f.name.trim())
    try {
      await createTemplate({
        typeName: form.get('typeName') as string,
        fields: validFields,
      })
      toast.success('Template created')
      setDialogOpen(false)
      setFields([{ name: '', type: 'text', required: false }])
      fetchTemplates()
    } catch {
      toast.error('Failed to create template')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900 dark:text-white">Templates</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">{templates.length} record templates</p>
        </div>
        <button onClick={() => setDialogOpen(true)} className="btn btn-primary text-sm px-3 py-1.5 flex items-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />New Template
        </button>
      </div>

      {/* Create dialog */}
      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="card p-6 w-full max-w-lg mx-4">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Create Record Template</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Type Name (e.g. "quality issue")</label>
                <input name="typeName" required className="input w-full" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Fields</label>
                <div className="space-y-2">
                  {fields.map((field, i) => (
                    <div key={i} className="flex gap-2 items-center">
                      <input
                        placeholder="Field name"
                        value={field.name}
                        onChange={(e) => { const nf = [...fields]; nf[i].name = e.target.value; setFields(nf) }}
                        className="input flex-1"
                      />
                      <select
                        value={field.type}
                        onChange={(e) => { const nf = [...fields]; nf[i].type = e.target.value; setFields(nf) }}
                        className="input w-auto px-2"
                      >
                        <option value="text">Text</option>
                        <option value="dropdown">Dropdown</option>
                        <option value="date">Date</option>
                        <option value="boolean">Yes/No</option>
                        <option value="number">Number</option>
                      </select>
                      <label className="flex items-center gap-1 text-sm whitespace-nowrap text-slate-600 dark:text-slate-400">
                        <input
                          type="checkbox"
                          checked={field.required}
                          onChange={(e) => { const nf = [...fields]; nf[i].required = e.target.checked; setFields(nf) }}
                          className="rounded"
                        />
                        Req
                      </label>
                    </div>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => setFields([...fields, { name: '', type: 'text', required: false }])}
                  className="btn btn-secondary text-sm px-2 py-1 mt-2 flex items-center gap-1"
                >
                  <Plus className="h-3 w-3" />Add Field
                </button>
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
      ) : templates.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <BookText className="h-10 w-10 text-slate-300 dark:text-slate-600 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">No templates yet</p>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-800/50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Type</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Project</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Fields</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {templates.map((t) => (
                <tr key={t.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                  <td className="px-4 py-2.5 font-semibold text-slate-800 dark:text-slate-200">{t.typeName}</td>
                  <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                    {t.projectId ? <span className="font-mono text-xs">{t.projectId.code}</span> : <span className="text-xs italic">Global</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {t.fields.map((f) => (
                        <span
                          key={f.name}
                          className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium ${
                            f.required
                              ? 'bg-sign-500/10 text-sign-600 border border-sign-500/20 dark:text-sign-400'
                              : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                          }`}
                        >
                          {f.name}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <WaStatusBadge status={t.isActive ? 'active' : 'archived'} size="sm" />
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
