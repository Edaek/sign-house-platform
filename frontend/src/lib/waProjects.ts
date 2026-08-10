import type { WaProject } from '../store/waStore'

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
