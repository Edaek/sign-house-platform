import { useEffect, useRef, useState } from 'react'
import { Palette } from 'lucide-react'
import clsx from 'clsx'
import {
  MARKER_COLOR_DOT,
  MARKER_COLOR_OPTIONS,
  MARKER_COLOR_STYLES,
  toggleMarkerColorSelection,
  type MarkerColor,
} from '../lib/markerColors'

interface MarkerColorMenuProps {
  colors: MarkerColor[]
  onChange: (colors: MarkerColor[]) => void
  variant?: 'compact' | 'toolbar'
}

export default function MarkerColorMenu({
  colors,
  onChange,
  variant = 'compact',
}: MarkerColorMenuProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const toggleColor = (color: MarkerColor) => {
    onChange(toggleMarkerColorSelection(colors, color))
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={clsx(
          'transition-colors',
          variant === 'toolbar'
            ? clsx(
                'flex items-center gap-2 px-4 py-2 rounded-lg',
                open
                  ? 'bg-sign-500/15 text-sign-700 dark:text-sign-300 ring-1 ring-sign-500/30'
                  : 'bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200',
              )
            : clsx(
                'p-2 rounded-lg',
                open
                  ? 'bg-sign-500/15 text-sign-600 dark:text-sign-400'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
              ),
        )}
        title="Marker colors"
      >
        <Palette className={variant === 'toolbar' ? 'w-4 h-4' : 'w-5 h-5'} />
        {variant === 'toolbar' && (
          <>
            <span className="text-sm font-medium">Marker colors</span>
            <span className="flex items-center gap-1 pl-0.5">
              {MARKER_COLOR_OPTIONS.map((color) => (
                <span
                  key={color}
                  className={clsx(
                    'w-2.5 h-2.5 rounded-full transition-all',
                    colors.includes(color)
                      ? MARKER_COLOR_DOT[color]
                      : 'bg-slate-300/40 dark:bg-slate-600/50 ring-1 ring-slate-400/40 dark:ring-slate-500/50',
                  )}
                  aria-hidden
                />
              ))}
            </span>
          </>
        )}
      </button>

      {open && (
        <div
          className={clsx(
            'absolute top-full mt-1.5 z-50 p-3 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg',
            variant === 'toolbar' ? 'right-0 w-56' : 'right-0 w-56',
          )}
        >
          <p className="text-xs font-medium text-slate-700 dark:text-slate-300 mb-2">
            Marker colors
          </p>
          <div className="flex gap-2">
            {MARKER_COLOR_OPTIONS.map((color) => {
              const selected = colors.includes(color)
              return (
                <button
                  key={color}
                  type="button"
                  onClick={() => toggleColor(color)}
                  className={clsx(
                    'flex-1 px-2 py-1.5 rounded-lg text-xs font-medium border transition-colors capitalize',
                    selected
                      ? MARKER_COLOR_STYLES[color].selected
                      : MARKER_COLOR_STYLES[color].unselected,
                    !selected && 'bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700',
                  )}
                >
                  {color}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
