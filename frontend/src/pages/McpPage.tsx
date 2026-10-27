import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Copy, Pencil, Plug2, Plus, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import PageContainer from '../components/PageContainer'
import api from '../lib/api'

type Transport = 'sse' | 'http' | 'stdio'

interface McpServer {
  id: string
  name: string
  transport: Transport
  url?: string | null
  command?: string | null
  args?: string[]
  headers?: Record<string, string>
  enabled: boolean
  createdAt?: string
  updatedAt?: string
}

interface HeaderRow {
  key: string
  value: string
}

const emptyForm = (): {
  name: string
  transport: Transport
  url: string
  command: string
  argsText: string
  headers: HeaderRow[]
  enabled: boolean
} => ({
  name: '',
  transport: 'sse',
  url: '',
  command: '',
  argsText: '',
  headers: [{ key: '', value: '' }],
  enabled: true,
})

function headersToRows(headers?: Record<string, string>): HeaderRow[] {
  const entries = Object.entries(headers || {})
  if (!entries.length) return [{ key: '', value: '' }]
  return entries.map(([key, value]) => ({ key, value }))
}

function rowsToHeaders(rows: HeaderRow[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const row of rows) {
    const k = row.key.trim()
    if (k) out[k] = row.value
  }
  return out
}

/** Sign House main app API (WA REST); MCP tools call this with the user's JWT. */
function defaultWaApiUrl(): string {
  const main = import.meta.env.VITE_SIGN_HOUSE_API_URL?.trim()
  if (main) {
    const t = main.replace(/\/$/, '')
    return t.endsWith('/api') ? t : `${t}/api`
  }
  return 'https://signhousev3.axilogy.io/api'
}

/** Hosted MCP on this repo's backend (/mcp). Same UI — no separate MCP site. */
function defaultWaMcpUrl(): string {
  const publicUrl = import.meta.env.VITE_MCP_PUBLIC_URL?.trim()
  if (publicUrl) {
    const u = publicUrl.replace(/\/$/, '')
    return u.endsWith('/mcp') ? `${u}/` : `${u}/mcp/`
  }
  const devProxy = import.meta.env.VITE_DEV_API_PROXY?.trim()
  if (devProxy) {
    return `${devProxy.replace(/\/$/, '')}/mcp/`
  }
  const apiUrl = import.meta.env.VITE_API_URL?.trim()
  if (apiUrl) {
    return `${apiUrl.replace(/\/$/, '')}/mcp/`
  }
  if (typeof window !== 'undefined') {
    return `${window.location.origin}/mcp/`
  }
  return 'http://127.0.0.1:5002/mcp/'
}

function tokenFromBrowserSession(): string {
  try {
    const raw = localStorage.getItem('auth-storage')
    if (!raw) return ''
    const parsed = JSON.parse(raw) as { state?: { token?: string } }
    return parsed?.state?.token?.trim() || ''
  } catch {
    return ''
  }
}

/** Ensure URL ends with /api (fixes truncated …/a typos). */
function normalizeWaApiUrl(input: string): string {
  const t = input.trim()
  if (!t) return defaultWaApiUrl()
  const noTrail = t.replace(/\/+$/, '')
  if (noTrail.endsWith('/api')) return noTrail
  if (noTrail.endsWith('/a')) return `${noTrail.slice(0, -1)}api`
  return `${noTrail}/api`
}

function waPresetHeadersUrl(): HeaderRow[] {
  const jwt = tokenFromBrowserSession()
  return [{ key: 'Authorization', value: jwt ? `Bearer ${jwt}` : 'Bearer ' }]
}

function normalizeWaPresetHeaders(rows: HeaderRow[]): HeaderRow[] {
  return rows.map((row) => {
    if (row.key.trim() === 'SIGN_HOUSE_API_URL') {
      return { ...row, value: normalizeWaApiUrl(row.value) }
    }
    return row
  })
}

function isSignHouseWaForm(form: { name: string }): boolean {
  return form.name.trim() === 'sign-house-wa'
}

function applyWaPreset() {
  return {
    ...emptyForm(),
    name: 'sign-house-wa',
    transport: 'http' as Transport,
    url: defaultWaMcpUrl(),
    command: '',
    argsText: '',
    headers: waPresetHeadersUrl(),
    enabled: true,
  }
}

export default function McpPage() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<McpServer | null>(null)
  const [form, setForm] = useState(emptyForm())
  const [saving, setSaving] = useState(false)
  const [waPresetOpen, setWaPresetOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await api.get<McpServer[]>('/mcp/servers')
      setServers(data)
    } catch {
      toast.error('Failed to load MCP servers')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function openCreate() {
    setEditing(null)
    setForm(emptyForm())
    setModalOpen(true)
  }

  function openWaPreset() {
    setEditing(null)
    setForm(applyWaPreset())
    setModalOpen(true)
    const jwt = tokenFromBrowserSession()
    toast.success(
      jwt
        ? 'Preset loaded — JWT filled from this browser session'
        : 'Preset loaded — log in first, then use “Refresh JWT” in the form',
    )
  }

  function refreshWaJwtInForm() {
    const jwt = tokenFromBrowserSession()
    if (form.transport === 'stdio') {
      const headers = form.headers.map((row) =>
        row.key.trim() === 'SIGN_HOUSE_JWT' ? { ...row, value: jwt } : row,
      )
      const hasJwtRow = headers.some((r) => r.key.trim() === 'SIGN_HOUSE_JWT')
      setForm({
        ...form,
        headers: hasJwtRow ? headers : [...headers, { key: 'SIGN_HOUSE_JWT', value: jwt }],
      })
    } else {
      setForm({
        ...form,
        headers: [{ key: 'Authorization', value: jwt ? `Bearer ${jwt}` : 'Bearer ' }],
      })
    }
    if (jwt) toast.success('JWT updated from auth-storage')
    else toast.error('No token in auth-storage — log in to Sign House first')
  }

  function resetWaApiUrlInForm() {
    if (isSignHouseWaForm(form) && (form.transport === 'http' || form.transport === 'sse')) {
      setForm({ ...form, url: defaultWaMcpUrl() })
      toast.success(`MCP URL set to ${defaultWaMcpUrl()}`)
      return
    }
    const url = defaultWaApiUrl()
    const headers = form.headers.map((row) =>
      row.key.trim() === 'SIGN_HOUSE_API_URL' ? { ...row, value: url } : row,
    )
    const hasUrlRow = headers.some((r) => r.key.trim() === 'SIGN_HOUSE_API_URL')
    setForm({
      ...form,
      headers: hasUrlRow ? headers : [...headers, { key: 'SIGN_HOUSE_API_URL', value: url }],
    })
    toast.success(`API URL set to ${url}`)
  }

  function openEdit(server: McpServer) {
    setEditing(server)
    setForm({
      name: server.name,
      transport: server.transport,
      url: server.url || '',
      command: server.command || '',
      argsText: (server.args || []).join(' '),
      headers: headersToRows(server.headers),
      enabled: server.enabled,
    })
    setModalOpen(true)
  }

  function closeModal() {
    setModalOpen(false)
    setEditing(null)
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    const headerRows = isSignHouseWaForm(form) ? normalizeWaPresetHeaders(form.headers) : form.headers
    const payload = {
      name: form.name.trim(),
      transport: form.transport,
      url: form.url.trim() || null,
      command: form.command.trim() || null,
      args: form.argsText.trim() ? form.argsText.trim().split(/\s+/) : [],
      headers: rowsToHeaders(headerRows),
      enabled: form.enabled,
    }
    if (isSignHouseWaForm(form) && form.transport === 'stdio' && !payload.headers.SIGN_HOUSE_JWT) {
      toast.error('SIGN_HOUSE_JWT is required — click Refresh JWT or log in')
      setSaving(false)
      return
    }
    if (
      isSignHouseWaForm(form) &&
      (form.transport === 'http' || form.transport === 'sse') &&
      !payload.headers.Authorization?.startsWith('Bearer ')
    ) {
      toast.error('Authorization: Bearer … is required — click Refresh JWT')
      setSaving(false)
      return
    }
    try {
      if (editing) {
        await api.put(`/mcp/servers/${editing.id}`, payload)
        toast.success('Updated')
      } else {
        await api.post('/mcp/servers', payload)
        toast.success('Added')
      }
      closeModal()
      await load()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error
      toast.error(msg || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(server: McpServer) {
    if (!window.confirm(`Delete MCP server "${server.name}"?`)) return
    try {
      await api.delete(`/mcp/servers/${server.id}`)
      toast.success('Deleted')
      await load()
    } catch {
      toast.error('Delete failed')
    }
  }

  async function handleCopy(server: McpServer) {
    try {
      const { data } = await api.get<{
        json?: string
        name?: string
        entry?: Record<string, unknown>
        snippet?: { mcpServers?: Record<string, unknown> }
      }>(`/mcp/servers/${server.id}/export`)

      let text: string
      if (data.name && data.entry) {
        text = JSON.stringify({ [data.name]: data.entry }, null, 2)
      } else if (data.snippet?.mcpServers) {
        text = JSON.stringify(data.snippet.mcpServers, null, 2)
      } else if (data.json) {
        try {
          const parsed = JSON.parse(data.json) as Record<string, unknown>
          if (parsed.mcpServers && typeof parsed.mcpServers === 'object') {
            text = JSON.stringify(parsed.mcpServers, null, 2)
          } else {
            text = data.json
          }
        } catch {
          text = data.json
        }
      } else {
        toast.error('Copy failed')
        return
      }

      await navigator.clipboard.writeText(text)
      toast.success('Copied (paste inside mcpServers in Cursor)')
    } catch {
      toast.error('Copy failed')
    }
  }

  return (
    <PageContainer>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="page-title flex items-center gap-2">
              <Plug2 className="h-8 w-8 text-sign-500" />
              MCP
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
              Manage your personal MCP server connections (URL, auth headers, enabled state). Configurations are
              visible only to you. Copy a snippet and paste it into Cursor&apos;s{' '}
              <code className="text-xs bg-slate-100 dark:bg-slate-800 px-1 rounded">mcp.json</code>
              . Secrets are masked in the list; full values appear only when you export or copy.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={openCreate} className="btn btn-primary text-sm px-4 py-2 inline-flex items-center gap-2">
              <Plus className="h-4 w-4" />
              Add server
            </button>
          </div>
        </div>

        <div className="card p-4">
          <button
            type="button"
            className="w-full flex items-center justify-between text-left gap-2"
            onClick={() => setWaPresetOpen((o) => !o)}
          >
            <span className="font-medium text-slate-900 dark:text-white">Recommended: Sign House WhatsApp (URL)</span>
            {waPresetOpen ? <ChevronUp className="h-4 w-4 shrink-0" /> : <ChevronDown className="h-4 w-4 shrink-0" />}
          </button>
          {waPresetOpen && (
            <div className="mt-3 text-sm text-slate-600 dark:text-slate-400 space-y-3">
              <p>
                Hosted on the same backend as Sign House. Transport <strong>HTTP</strong>, URL below, header{' '}
                <span className="font-mono">Authorization: Bearer …</span> from your login.
              </p>
              <p className="text-xs font-mono break-all bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded">
                {defaultWaMcpUrl()}
              </p>
              <button type="button" onClick={openWaPreset} className="btn btn-secondary text-sm">
                Use Sign House WA preset
              </button>
            </div>
          )}
        </div>

        <div className="card overflow-hidden">
          {loading ? (
            <div className="p-12 flex justify-center">
              <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
            </div>
          ) : servers.length === 0 ? (
            <div className="p-12 text-center text-slate-500 dark:text-slate-400">
              No MCP servers yet. Click &quot;Add server&quot; to get started.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 dark:bg-slate-800/50 text-left text-xs uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Transport</th>
                    <th className="px-4 py-3">Endpoint</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                  {servers.map((s) => (
                    <tr key={s.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/30">
                      <td className="px-4 py-3 font-medium text-slate-900 dark:text-white">{s.name}</td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-300 uppercase text-xs">{s.transport}</td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-300 max-w-md truncate font-mono text-xs">
                        {s.transport === 'stdio' ? s.command : s.url}
                      </td>
                      <td className="px-4 py-3">
                        <span className={clsx(
                          'text-xs px-2 py-0.5 rounded-full',
                          s.enabled
                            ? 'bg-sign-100 text-sign-700 dark:bg-sign-900/30 dark:text-sign-400'
                            : 'bg-slate-100 text-slate-500 dark:bg-slate-800',
                        )}
                        >
                          {s.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <button
                            type="button"
                            title="Copy Cursor config"
                            onClick={() => handleCopy(s)}
                            className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                          >
                            <Copy className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            title="Edit"
                            onClick={() => openEdit(s)}
                            className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            title="Delete"
                            onClick={() => handleDelete(s)}
                            className="p-2 rounded-lg text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
          <div className="card w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                {editing ? 'Edit MCP server' : 'Add MCP server'}
              </h2>
              <button type="button" onClick={closeModal} className="p-1 text-slate-400 hover:text-slate-600">
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <label className="label">Name (mcp.json key)</label>
                <input
                  className="input w-full"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Kanban"
                  required
                  pattern="[A-Za-z0-9_-]{1,64}"
                />
              </div>
              <div>
                <label className="label">Transport</label>
                <select
                  className="input w-full"
                  value={form.transport}
                  onChange={(e) => setForm({ ...form, transport: e.target.value as Transport })}
                >
                  <option value="sse">SSE</option>
                  <option value="http">HTTP</option>
                  <option value="stdio">stdio</option>
                </select>
              </div>
              {(form.transport === 'sse' || form.transport === 'http') && (
                <div>
                  <label className="label">URL</label>
                  <input
                    className="input w-full font-mono text-sm"
                    value={form.url}
                    onChange={(e) => setForm({ ...form, url: e.target.value })}
                    placeholder="https://example.com/mcp"
                    required
                  />
                </div>
              )}
              {form.transport === 'stdio' && (
                <>
                  <div>
                    <label className="label">Command</label>
                    <input
                      className="input w-full font-mono text-sm"
                      value={form.command}
                      onChange={(e) => setForm({ ...form, command: e.target.value })}
                      placeholder={isSignHouseWaForm(form) ? '…/backend/.venv/bin/python' : 'npx'}
                      required
                    />
                  </div>
                  <div>
                    <label className="label">Args (space-separated)</label>
                    <input
                      className="input w-full font-mono text-sm"
                      value={form.argsText}
                      onChange={(e) => setForm({ ...form, argsText: e.target.value })}
                      placeholder="-y @org/mcp-server"
                    />
                  </div>
                </>
              )}
              <div>
                <label className="label">
                  {form.transport === 'stdio' ? 'Environment variables (stdio → Cursor env)' : 'HTTP headers (optional)'}
                </label>
                {isSignHouseWaForm(form) && (
                  <div className="flex flex-wrap gap-2 mb-2">
                    <button type="button" className="text-xs btn btn-secondary py-1 px-2" onClick={refreshWaJwtInForm}>
                      Refresh JWT
                    </button>
                    <button type="button" className="text-xs btn btn-secondary py-1 px-2" onClick={resetWaApiUrlInForm}>
                      {form.transport === 'stdio' ? 'Reset API URL' : 'Reset MCP URL'}
                    </button>
                  </div>
                )}
                <div className="space-y-3">
                  {form.headers.map((row, idx) =>
                    form.transport === 'stdio' ? (
                      <div key={idx} className="space-y-1">
                        <input
                          className="input w-full text-sm font-mono"
                          placeholder="VAR_NAME"
                          value={row.key}
                          onChange={(e) => {
                            const headers = [...form.headers]
                            headers[idx] = { ...headers[idx], key: e.target.value }
                            setForm({ ...form, headers })
                          }}
                        />
                        <input
                          className="input w-full text-sm font-mono"
                          placeholder={
                            row.key.trim() === 'SIGN_HOUSE_JWT'
                              ? 'eyJ… (from auth-storage state.token)'
                              : row.key.trim() === 'SIGN_HOUSE_API_URL'
                                ? defaultWaApiUrl()
                                : 'Value'
                          }
                          value={row.value}
                          onChange={(e) => {
                            const headers = [...form.headers]
                            headers[idx] = { ...headers[idx], value: e.target.value }
                            setForm({ ...form, headers })
                          }}
                        />
                      </div>
                    ) : (
                      <div key={idx} className="flex gap-2">
                        <input
                          className="input flex-1 text-sm"
                          placeholder="Header name"
                          value={row.key}
                          onChange={(e) => {
                            const headers = [...form.headers]
                            headers[idx] = { ...headers[idx], key: e.target.value }
                            setForm({ ...form, headers })
                          }}
                        />
                        <input
                          className="input flex-1 text-sm font-mono"
                          placeholder="Value"
                          value={row.value}
                          onChange={(e) => {
                            const headers = [...form.headers]
                            headers[idx] = { ...headers[idx], value: e.target.value }
                            setForm({ ...form, headers })
                          }}
                        />
                      </div>
                    ),
                  )}
                  <button
                    type="button"
                    className="text-xs text-sign-600 dark:text-sign-400"
                    onClick={() => setForm({ ...form, headers: [...form.headers, { key: '', value: '' }] })}
                  >
                    + Add {form.transport === 'stdio' ? 'variable' : 'header'}
                  </button>
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                />
                Enabled
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={closeModal} className="btn btn-secondary text-sm">
                  Cancel
                </button>
                <button type="submit" disabled={saving} className="btn btn-primary text-sm">
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </PageContainer>
  )
}
