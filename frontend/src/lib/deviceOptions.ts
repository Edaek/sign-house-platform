export const DEVICE_OPTIONS = ['cpu', 'gpu:0'] as const
export type PaddleDevice = (typeof DEVICE_OPTIONS)[number]

export const DEFAULT_DEVICE: PaddleDevice = 'cpu'

export interface ComputeDeviceGpuInfo {
  available: boolean
  count: number
  names: string[]
  cuda_version: string | null
  error: string | null
}

export interface ComputeDevicesInfo {
  cpu: { available: boolean; error?: string | null }
  gpu: ComputeDeviceGpuInfo
  gpu_only?: boolean
  paddle_package: string
  paddle_version: string | null
  default_device: string
  recommended: string[]
}

export function deviceLabel(device: string): string {
  if (device === 'cpu') return 'CPU'
  if (device.startsWith('gpu')) return 'GPU'
  return device.toUpperCase()
}
