import type { PoolImage } from '../store/waStore'

export function poolFileSrc(photo: string) {
  return photo.startsWith('/uploads/') ? `/api/wa/uploads${photo.replace('/uploads', '')}` : photo
}

export function poolDisplayName(img: PoolImage): string {
  if (img.fileName) return img.fileName
  if (img.imagePath) {
    const part = img.imagePath.split('/').pop() || img.imagePath
    return part.split('?')[0]
  }
  return 'File'
}

export function poolMediaKind(img: PoolImage): 'image' | 'document' | 'video' | 'file' {
  const t = img.mediaType
  if (t === 'image' || t === 'document' || t === 'video' || t === 'file') return t
  const name = poolDisplayName(img).toLowerCase()
  if (/\.(jpe?g|png|gif|webp|heic|bmp)$/i.test(name)) return 'image'
  if (/\.(pdf|docx?|xlsx?|pptx?|txt|csv)$/i.test(name)) return 'document'
  if (/\.(mp4|mov|3gp|webm)$/i.test(name)) return 'video'
  return 'file'
}

export function poolIsPreviewableImage(img: PoolImage): boolean {
  return poolMediaKind(img) === 'image'
}

export function poolFileExtension(img: PoolImage): string {
  const m = poolDisplayName(img).match(/\.([a-z0-9]+)$/i)
  return m ? m[1].toUpperCase() : 'FILE'
}
