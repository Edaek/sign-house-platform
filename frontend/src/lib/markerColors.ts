export const MARKER_COLOR_OPTIONS = ['red', 'blue', 'yellow'] as const

export type MarkerColor = (typeof MARKER_COLOR_OPTIONS)[number]

export const DEFAULT_MARKER_COLORS: MarkerColor[] = [...MARKER_COLOR_OPTIONS]

export const MARKER_COLOR_DOT: Record<MarkerColor, string> = {
  red: 'bg-red-500',
  blue: 'bg-blue-500',
  yellow: 'bg-yellow-500',
}

export const MARKER_COLOR_CANVAS: Record<
  MarkerColor,
  { stroke: string; fill: string }
> = {
  red: { stroke: '#ef4444', fill: 'rgba(239, 68, 68, 0.12)' },
  blue: { stroke: '#3b82f6', fill: 'rgba(59, 130, 246, 0.12)' },
  yellow: { stroke: '#eab308', fill: 'rgba(234, 179, 8, 0.16)' },
}

export function resolveMarkerColor(value?: string | null): MarkerColor | null {
  if (value === 'red' || value === 'blue' || value === 'yellow') return value
  return null
}

export const MARKER_COLOR_STYLES: Record<
  MarkerColor,
  { selected: string; unselected: string }
> = {
  red: {
    selected: 'bg-red-500 text-white border-red-500',
    unselected: 'border-red-300 text-red-600 dark:border-red-700 dark:text-red-400',
  },
  blue: {
    selected: 'bg-blue-500 text-white border-blue-500',
    unselected: 'border-blue-300 text-blue-600 dark:border-blue-700 dark:text-blue-400',
  },
  yellow: {
    selected: 'bg-yellow-500 text-white border-yellow-500',
    unselected: 'border-yellow-300 text-yellow-700 dark:border-yellow-700 dark:text-yellow-400',
  },
}

export function toggleMarkerColorSelection(
  current: MarkerColor[],
  color: MarkerColor,
): MarkerColor[] {
  if (current.includes(color)) {
    if (current.length === 1) return current
    return current.filter((c) => c !== color)
  }
  return [...current, color]
}
