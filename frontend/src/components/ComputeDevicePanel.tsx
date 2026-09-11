import { useState } from 'react'
import clsx from 'clsx'
import { RefreshCw, Cpu, Zap, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import type { ComputeDevicesInfo } from '../lib/deviceOptions'
import { deviceLabel } from '../lib/deviceOptions'

interface ComputeDevicePanelProps {
  computeDevices: ComputeDevicesInfo | null
  paddleDevice: string
  onDeviceChange: (device: string) => void
  onRefresh: (force?: boolean) => Promise<ComputeDevicesInfo | null>
  className?: string
}

export default function ComputeDevicePanel({
  computeDevices,
  paddleDevice,
  onDeviceChange,
  onRefresh,
  className,
}: ComputeDevicePanelProps) {
  const [isChecking, setIsChecking] = useState(false)

  const handleCheck = async () => {
    setIsChecking(true)
    try {
      const info = await onRefresh(true)
      if (info) {
        toast.success('Device check completed')
        if (!info.recommended.includes(paddleDevice)) {
          onDeviceChange(info.default_device)
        }
      } else {
        toast.error('Device check failed')
      }
    } finally {
      setIsChecking(false)
    }
  }

  const gpu = computeDevices?.gpu
  const gpuOnly = computeDevices?.gpu_only ?? false
  const recommended = computeDevices?.recommended ?? ['cpu']
  const gpuAvailable = recommended.includes('gpu:0')
  const showCpu = !gpuOnly && recommended.includes('cpu')

  const gpuStatus = gpu?.available
    ? `${gpu.count} GPU${gpu.count !== 1 ? 's' : ''}${gpu.names?.[0] ? ` · ${gpu.names[0]}` : ''}`
    : (gpu?.error ?? 'Not detected')

  return (
    <div className={clsx(
      'rounded-xl border border-slate-200/80 dark:border-slate-700/80',
      'bg-gradient-to-r from-slate-50 to-white dark:from-slate-800/50 dark:to-slate-800',
      'px-4 py-3 sm:px-5 sm:py-4',
      className,
    )}>
      <div className="flex flex-col lg:flex-row lg:items-center gap-4">
        {/* Title block */}
        <div className="flex items-center gap-3 min-w-0 lg:flex-1">
          <div className={clsx(
            'w-10 h-10 rounded-lg flex items-center justify-center shrink-0',
            paddleDevice.startsWith('gpu')
              ? 'bg-sign-500/15 text-sign-600 dark:text-sign-400'
              : 'bg-slate-200/80 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
          )}>
            {paddleDevice.startsWith('gpu') ? (
              <Zap className="w-5 h-5" />
            ) : (
              <Cpu className="w-5 h-5" />
            )}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-900 dark:text-white">
              OCR Engine
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
              All projects use {deviceLabel(paddleDevice)} for text recognition
            </p>
          </div>
        </div>

        {/* Stats pills */}
        {computeDevices && (
          <div className="flex flex-wrap gap-2 lg:flex-1 lg:justify-center">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300">
              Paddle {computeDevices.paddle_package}
              {computeDevices.paddle_version ? ` ${computeDevices.paddle_version}` : ''}
            </span>
            <span className={clsx(
              'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border max-w-xs truncate',
              gpu?.available
                ? 'bg-sign-500/10 border-sign-500/25 text-sign-700 dark:text-sign-300'
                : 'bg-slate-100 dark:bg-slate-900 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400',
            )} title={gpuStatus}>
              {gpuStatus}
            </span>
            {gpuOnly && (
              <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 border border-amber-500/25 text-amber-700 dark:text-amber-300">
                GPU only
              </span>
            )}
          </div>
        )}

        {/* Controls */}
        <div className="flex items-center gap-2 shrink-0 lg:justify-end">
          <div className="inline-flex p-0.5 rounded-lg bg-slate-200/70 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-600">
            {showCpu && (
              <button
                type="button"
                onClick={() => onDeviceChange('cpu')}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                  paddleDevice === 'cpu'
                    ? 'bg-white dark:bg-slate-700 text-sign-600 dark:text-sign-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white',
                )}
              >
                <Cpu className="w-3.5 h-3.5" />
                CPU
              </button>
            )}
            <button
              type="button"
              onClick={() => gpuAvailable && onDeviceChange('gpu:0')}
              disabled={!gpuAvailable}
              title={gpuAvailable ? (gpu?.names?.[0] ?? 'GPU') : (gpu?.error ?? 'GPU unavailable')}
              className={clsx(
                'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                paddleDevice.startsWith('gpu') && gpuAvailable
                  ? 'bg-white dark:bg-slate-700 text-sign-600 dark:text-sign-400 shadow-sm'
                  : gpuAvailable
                    ? 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                    : 'text-slate-400 dark:text-slate-600 cursor-not-allowed',
              )}
            >
              <Zap className="w-3.5 h-3.5" />
              GPU
            </button>
          </div>
          <button
            type="button"
            onClick={handleCheck}
            disabled={isChecking}
            title="Re-detect CPU/GPU availability"
            className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            {isChecking ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
