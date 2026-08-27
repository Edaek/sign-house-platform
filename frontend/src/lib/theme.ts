/** Shared theme tokens and status color mappings. */

export const statusStyles: Record<string, string> = {
  completed:
    'bg-sign-600/15 text-sign-800 border-sign-600/25 dark:bg-sign-500/20 dark:text-sign-300 dark:border-sign-500/30',
  in_progress:
    'bg-sign-500/15 text-sign-700 border-sign-500/25 dark:bg-sign-500/20 dark:text-sign-400 dark:border-sign-500/30',
  processing:
    'bg-sign-500/15 text-sign-700 border-sign-500/25 dark:bg-sign-500/20 dark:text-sign-400 dark:border-sign-500/30',
  pending:
    'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-600',
  draft:
    'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-600',
  error:
    'bg-red-500/15 text-red-700 border-red-500/25 dark:bg-red-500/20 dark:text-red-400 dark:border-red-500/30',
  incomplete:
    'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600',
  followup:
    'bg-sign-500/15 text-sign-700 border-sign-500/25 dark:bg-sign-500/20 dark:text-sign-400 dark:border-sign-500/30',
  awaiting_review:
    'bg-sign-500/15 text-sign-700 border-sign-500/25 dark:bg-sign-500/20 dark:text-sign-400 dark:border-sign-500/30',
  voided:
    'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-800/50 dark:text-slate-500 dark:border-slate-700',
  active:
    'bg-sign-500/15 text-sign-700 border-sign-500/25 dark:bg-sign-500/20 dark:text-sign-400 dark:border-sign-500/30',
  planning:
    'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600',
  hold:
    'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600',
  archived:
    'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-800/50 dark:text-slate-500 dark:border-slate-700',
}

export const defaultStatusStyle =
  'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-600'

export function getStatusStyle(status: string): string {
  return statusStyles[status] ?? defaultStatusStyle
}

export function formatStatusLabel(status: string): string {
  return status
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

/** Audit log action badge colors */
export function getActionColor(action: string): string {
  if (action.includes('deleted') || action.includes('deactivated')) {
    return 'bg-red-500/15 text-red-700 dark:bg-red-500/20 dark:text-red-400'
  }
  if (action.includes('login') || action.includes('registered') || action.includes('created')) {
    return 'bg-sign-500/15 text-sign-700 dark:bg-sign-500/20 dark:text-sign-400'
  }
  if (action.includes('updated') || action.includes('changed')) {
    return 'bg-sign-300/25 text-sign-800 dark:bg-sign-500/10 dark:text-sign-300'
  }
  return defaultStatusStyle
}

/** Processing pipeline step colors (progress bars / icons) */
export const processingSteps: Record<string, { icon: string; bar: string }> = {
  pending: { icon: 'text-slate-400', bar: 'bg-slate-400' },
  uploading: { icon: 'text-sign-300 animate-pulse', bar: 'bg-sign-300' },
  converting: { icon: 'text-sign-400 animate-pulse', bar: 'bg-sign-400' },
  detecting: { icon: 'text-sign-500 animate-pulse', bar: 'bg-sign-500' },
  ocr: { icon: 'text-sign-600 animate-pulse', bar: 'bg-sign-600' },
  completed: { icon: 'text-sign-500', bar: 'bg-sign-500' },
  error: { icon: 'text-red-400', bar: 'bg-red-500' },
  cancelled: { icon: 'text-amber-500', bar: 'bg-amber-400' },
}

export function getProcessingStepColor(status: string): { icon: string; bar: string } {
  return processingSteps[status] ?? processingSteps.pending
}
