import type { WaProject } from '../store/waStore'

/** Dropdown / list label — prefers NAS folder name (e.g. LIGHT-high) over redundant "CODE - CODE". */
export function formatWaProjectLabel(project: WaProject): string {
  const code = (project.code || '').trim()
  const name = (project.name || '').trim()
  const folder = (project.nasFolderName || '').trim()

  if (folder && folder.toLowerCase() !== code.toLowerCase()) {
    if (!name || name.toLowerCase() === code.toLowerCase()) {
      return folder
    }
    return `${folder} · ${name}`
  }
  if (!name || name.toLowerCase() === code.toLowerCase()) {
    return code
  }
  return `${code} - ${name}`
}

export function filterWaProjects(
  projects: WaProject[],
  query: string,
  stage?: string
): WaProject[] {
  const q = query.trim().toLowerCase()
  return projects.filter((project) => {
    if (stage && project.stage !== stage) return false
    if (!q) return true
    return (
      project.code.toLowerCase().includes(q) ||
      project.name.toLowerCase().includes(q) ||
      project.location?.toLowerCase().includes(q) ||
      project.status.toLowerCase().includes(q) ||
      project.stage.toLowerCase().includes(q)
    )
  })
}
