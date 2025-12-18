import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { 
  ChevronLeft,
  ChevronRight,
  Scan,
  Type,
  MousePointer,
  Square,
  Circle,
  Trash2,
  Edit3,
  Check,
  X,
  ZoomIn,
  ZoomOut,
  Move,
  Loader2
} from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import api from '../lib/api'
import toast from 'react-hot-toast'
import clsx from 'clsx'

interface DrawingRect {
  startX: number
  startY: number
  width: number
  height: number
}

export default function EditorPage() {
  const { projectId, floorId } = useParams<{ projectId: string; floorId: string }>()
  const navigate = useNavigate()
  const { 
    currentProject, 
    currentFloorplan, 
    fetchProject,
    fetchFloorplan, 
    detectShapes, 
    runOCR,
    ocrRegion,
    updateExtractedData,
    deleteExtractedData,
    updateFloorplan,
    deleteFloorplan,
    isLoading 
  } = useProjectStore()
  
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  
  const [tool, setTool] = useState<'select' | 'draw'>('select')
  const [shapeType, setShapeType] = useState<'auto' | 'circle' | 'rectangle'>('auto')
  const [scale, setScale] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const [panStart, setPanStart] = useState({ x: 0, y: 0 })
  
  const [isDrawing, setIsDrawing] = useState(false)
  const [drawingRect, setDrawingRect] = useState<DrawingRect | null>(null)
  const [selectedShape, setSelectedShape] = useState<string | null>(null)
  const [editingText, setEditingText] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [editingQuantity, setEditingQuantity] = useState<string | null>(null)
  const [editQuantity, setEditQuantity] = useState('')
  
  const [isEditingFloorName, setIsEditingFloorName] = useState(false)
  const [editedFloorName, setEditedFloorName] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  
  const [isDetectingShapes, setIsDetectingShapes] = useState(false)
  const [isRunningOCR, setIsRunningOCR] = useState(false)
  
  const [imageLoaded, setImageLoaded] = useState(false)
  
  // Fetch project and floorplan data
  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
    }
    if (projectId && floorId) {
      fetchFloorplan(projectId, floorId)
    }
  }, [projectId, floorId, fetchProject, fetchFloorplan])
  
  // Load floor plan image with authentication
  useEffect(() => {
    if (!currentFloorplan?.id || !floorId) return
    
    let blobUrl: string | null = null
    
    const loadImage = async () => {
      try {
        // Fetch image with auth headers using axios
        const response = await api.get(`/processing/image/${floorId}`, {
          responseType: 'blob'
        })
        
        blobUrl = URL.createObjectURL(response.data)
        
        const img = new Image()
        img.onload = () => {
          imageRef.current = img
          setImageLoaded(true)
          drawCanvas()
        }
        img.onerror = () => {
          toast.error('Failed to load floor plan image')
        }
        img.src = blobUrl
      } catch (error) {
        toast.error('Failed to load floor plan image')
      }
    }
    
    loadImage()
    
    return () => {
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl)
      }
    }
  }, [currentFloorplan?.id, floorId])
  
  // Draw canvas
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    const img = imageRef.current
    
    if (!canvas || !ctx || !img || !imageLoaded) return
    
    // Set canvas size
    const container = containerRef.current
    if (container) {
      canvas.width = container.clientWidth
      canvas.height = container.clientHeight
    }
    
    // Clear canvas - use appropriate background color
    const isDark = document.documentElement.classList.contains('dark')
    ctx.fillStyle = isDark ? '#1e293b' : '#f8fafc'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    
    // Draw image with transform
    ctx.save()
    ctx.translate(offset.x, offset.y)
    ctx.scale(scale, scale)
    ctx.drawImage(img, 0, 0)
    
    // Draw detected shapes
    if (currentFloorplan?.extracted_data) {
      currentFloorplan.extracted_data.forEach((shape, index) => {
        const isSelected = selectedShape === shape.id
        
        ctx.strokeStyle = isSelected ? '#ed751d' : '#3b9df6'
        ctx.lineWidth = isSelected ? 3 / scale : 2 / scale
        ctx.fillStyle = isSelected ? 'rgba(237, 117, 29, 0.1)' : 'rgba(59, 157, 246, 0.1)'
        
        // If this shape has merged bounding boxes, draw all of them
        const boxesToDraw = shape.all_bounding_boxes || [{
          x: shape.x,
          y: shape.y,
          width: shape.width,
          height: shape.height,
          shape_type: shape.shape_type,
          shape_data: shape.shape_data
        }]
        
        boxesToDraw.forEach((box) => {
          if (box.shape_type === 'circle' && box.shape_data?.radius) {
            const { center_x, center_y, radius } = box.shape_data
            if (center_x !== undefined && center_y !== undefined && radius !== undefined) {
              ctx.beginPath()
              ctx.arc(center_x, center_y, radius, 0, Math.PI * 2)
              ctx.fill()
              ctx.stroke()
            }
          } else {
            ctx.beginPath()
            ctx.rect(box.x, box.y, box.width, box.height)
            ctx.fill()
            ctx.stroke()
          }
        })
        
        // Draw shape number on the first box
        const firstBox = boxesToDraw[0]
        ctx.fillStyle = isSelected ? '#ed751d' : '#3b9df6'
        ctx.font = `bold ${14 / scale}px sans-serif`
        ctx.fillText(`${index + 1}`, firstBox.x + 4, firstBox.y + 16)
      })
    }
    
    // Draw current drawing rectangle
    if (drawingRect) {
      ctx.strokeStyle = '#ed751d'
      ctx.lineWidth = 2 / scale
      ctx.fillStyle = 'rgba(237, 117, 29, 0.2)'
      ctx.setLineDash([5 / scale, 5 / scale])
      ctx.beginPath()
      ctx.rect(drawingRect.startX, drawingRect.startY, drawingRect.width, drawingRect.height)
      ctx.fill()
      ctx.stroke()
      ctx.setLineDash([])
    }
    
    ctx.restore()
  }, [scale, offset, currentFloorplan?.extracted_data, selectedShape, drawingRect, imageLoaded])
  
  // Redraw on changes
  useEffect(() => {
    drawCanvas()
  }, [drawCanvas])
  
  // Handle resize
  useEffect(() => {
    const handleResize = () => drawCanvas()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [drawCanvas])
  
  // Handle wheel zoom with passive: false to prevent page scroll
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !imageLoaded) return
    
    const handleWheelEvent = (e: WheelEvent) => {
      e.preventDefault()
      const delta = e.deltaY > 0 ? 0.9 : 1.1
      const newScale = Math.min(Math.max(scale * delta, 0.1), 5)
      
      const rect = canvas.getBoundingClientRect()
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      
      setOffset(prev => ({
        x: mouseX - (mouseX - prev.x) * (newScale / scale),
        y: mouseY - (mouseY - prev.y) * (newScale / scale)
      }))
      
      setScale(newScale)
    }
    
    canvas.addEventListener('wheel', handleWheelEvent, { passive: false })
    return () => canvas.removeEventListener('wheel', handleWheelEvent)
  }, [scale, imageLoaded])
  
  // Get canvas coordinates from mouse event
  const getCanvasCoords = (e: React.MouseEvent) => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    
    const rect = canvas.getBoundingClientRect()
    const x = (e.clientX - rect.left - offset.x) / scale
    const y = (e.clientY - rect.top - offset.y) / scale
    
    return { x, y }
  }
  
  // Mouse handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    const coords = getCanvasCoords(e)
    
    if (e.button === 1 || (e.button === 0 && e.altKey)) {
      // Middle click or Alt+click for panning
      setIsPanning(true)
      setPanStart({ x: e.clientX - offset.x, y: e.clientY - offset.y })
      return
    }
    
    if (tool === 'draw') {
      setIsDrawing(true)
      setDrawingRect({ startX: coords.x, startY: coords.y, width: 0, height: 0 })
    } else {
      // Check if clicked on a shape (including all merged bounding boxes)
      const clickedShape = currentFloorplan?.extracted_data?.find(shape => {
        // If shape has merged bounding boxes, check all of them
        const boxesToCheck = shape.all_bounding_boxes || [{
          x: shape.x,
          y: shape.y,
          width: shape.width,
          height: shape.height
        }]
        
        // Check if click is within any of the boxes
        return boxesToCheck.some(box => 
          coords.x >= box.x && 
          coords.x <= box.x + box.width &&
          coords.y >= box.y && 
          coords.y <= box.y + box.height
        )
      })
      
      if (clickedShape) {
        setSelectedShape(clickedShape.id)
      } else {
        // If no shape clicked, start panning
        setSelectedShape(null)
        setIsPanning(true)
        setPanStart({ x: e.clientX - offset.x, y: e.clientY - offset.y })
      }
    }
  }
  
  const handleMouseMove = (e: React.MouseEvent) => {
    if (isPanning) {
      setOffset({
        x: e.clientX - panStart.x,
        y: e.clientY - panStart.y
      })
      return
    }
    
    if (isDrawing) {
      const coords = getCanvasCoords(e)
      setDrawingRect(prev => {
        if (!prev) return null
        return {
          ...prev,
          width: coords.x - prev.startX,
          height: coords.y - prev.startY
        }
      })
    }
  }
  
  const handleMouseUp = async () => {
    if (isPanning) {
      setIsPanning(false)
      return
    }
    
    if (isDrawing && drawingRect && floorId) {
      // Normalize rectangle (handle negative dimensions)
      const x = drawingRect.width >= 0 ? drawingRect.startX : drawingRect.startX + drawingRect.width
      const y = drawingRect.height >= 0 ? drawingRect.startY : drawingRect.startY + drawingRect.height
      const width = Math.abs(drawingRect.width)
      const height = Math.abs(drawingRect.height)
      
      if (width > 10 && height > 10) {
        try {
          await ocrRegion(floorId, { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) })
          toast.success('Text extracted!')
        } catch {
          toast.error('Failed to extract text')
        }
      }
    }
    
    setIsDrawing(false)
    setDrawingRect(null)
  }
  
  
  // Actions
  const handleDetectShapes = async () => {
    if (!floorId || isDetectingShapes) return
    
    setIsDetectingShapes(true)
    try {
      await detectShapes(floorId, shapeType)
      toast.success('Shapes detected!')
    } catch {
      toast.error('Shape detection failed')
    } finally {
      setIsDetectingShapes(false)
    }
  }
  
  const handleRunOCR = async () => {
    if (!floorId || isRunningOCR) return
    
    setIsRunningOCR(true)
    try {
      await runOCR(floorId)
      toast.success('OCR completed!')
    } catch {
      toast.error('OCR failed')
    } finally {
      setIsRunningOCR(false)
    }
  }
  
  const handleDeleteShape = async (id: string) => {
    try {
      await deleteExtractedData(id)
      setSelectedShape(null)
      toast.success('Shape deleted')
    } catch {
      toast.error('Failed to delete shape')
    }
  }
  
  const handleSaveText = async () => {
    if (editingText === null) return
    
    try {
      await updateExtractedData(editingText, editText)
      setEditingText(null)
      toast.success('Text updated')
    } catch {
      toast.error('Failed to update text')
    }
  }
  
  const handleSaveQuantity = async () => {
    if (editingQuantity === null) return
    
    const quantity = parseInt(editQuantity)
    if (isNaN(quantity) || quantity < 1) {
      toast.error('Quantity must be a positive number')
      return
    }
    
    try {
      await updateExtractedData(editingQuantity, undefined, quantity)
      setEditingQuantity(null)
      toast.success('Quantity updated')
    } catch {
      toast.error('Failed to update quantity')
    }
  }
  
  const handleSaveFloorName = async () => {
    if (!projectId || !floorId || !editedFloorName.trim()) return
    
    try {
      await updateFloorplan(projectId, floorId, { floor_name: editedFloorName.trim() })
      setIsEditingFloorName(false)
      toast.success('Floor name updated')
    } catch {
      toast.error('Failed to update floor name')
    }
  }
  
  const handleCancelFloorNameEdit = () => {
    setIsEditingFloorName(false)
    setEditedFloorName('')
  }
  
  const handleMarkComplete = async () => {
    if (!projectId || !floorId) return
    
    try {
      await updateFloorplan(projectId, floorId, { status: 'completed' })
      toast.success('Floor marked as complete!')
      
      // Navigate to next floor or export
      const currentIdx = currentProject?.floorplans?.findIndex(fp => fp.id === floorId)
      if (currentIdx !== undefined && currentProject?.floorplans) {
        if (currentIdx < currentProject.floorplans.length - 1) {
          const nextFloor = currentProject.floorplans[currentIdx + 1]
          navigate(`/project/${projectId}/floor/${nextFloor.id}`)
        } else {
          navigate(`/project/${projectId}/export`)
        }
      }
    } catch {
      toast.error('Failed to update status')
    }
  }
  
  const handleDeleteFloor = async () => {
    if (!projectId || !floorId) return
    
    try {
      await deleteFloorplan(projectId, floorId)
      toast.success('Floor deleted successfully')
      setShowDeleteConfirm(false)
      
      // Navigate to another floor or back to project
      const remainingFloors = currentProject?.floorplans?.filter(fp => fp.id !== floorId)
      if (remainingFloors && remainingFloors.length > 0) {
        // Navigate to first remaining floor
        navigate(`/project/${projectId}/floor/${remainingFloors[0].id}`)
      } else {
        // No floors left, go back to project page
        navigate(`/project/${projectId}`)
      }
    } catch {
      toast.error('Failed to delete floor')
    }
  }
  
  // Get adjacent floors for navigation
  const currentIndex = currentProject?.floorplans?.findIndex(fp => fp.id === floorId)
  const prevFloor = currentIndex !== undefined && currentIndex > 0 ? currentProject?.floorplans?.[currentIndex - 1] : null
  const nextFloor = currentIndex !== undefined && currentProject?.floorplans && currentIndex < currentProject.floorplans.length - 1 
    ? currentProject.floorplans[currentIndex + 1] 
    : null
  
  const selectedData = currentFloorplan?.extracted_data?.find(d => d.id === selectedShape)
  
  if (isLoading && !currentFloorplan) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-64px)]">
        <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
      </div>
    )
  }
  
  return (
    <div className="h-[calc(100vh-64px)] flex flex-col">
      {/* Top Bar */}
      <div className="h-14 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between px-4 sticky top-0 z-40">
        <div className="flex items-center gap-4">
          <Link 
            to={`/project/${projectId}`}
            className="flex items-center gap-1 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            Back
          </Link>
          
          <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />
          
          {isEditingFloorName ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={editedFloorName}
                onChange={(e) => setEditedFloorName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSaveFloorName()
                  if (e.key === 'Escape') handleCancelFloorNameEdit()
                }}
                className="input text-sm py-1.5 px-3 w-64"
                autoFocus
                placeholder="Floor name"
              />
              <button
                onClick={handleSaveFloorName}
                className="p-2 bg-emerald-500 text-white rounded-lg hover:bg-emerald-400 transition-colors"
                title="Save (Enter)"
              >
                <Check className="w-4 h-4" />
              </button>
              <button
                onClick={handleCancelFloorNameEdit}
                className="p-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors"
                title="Cancel (Esc)"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 group">
              <h2 className="font-medium text-slate-900 dark:text-white">
                {currentFloorplan?.floor_name}
              </h2>
              <button
                onClick={() => {
                  setIsEditingFloorName(true)
                  setEditedFloorName(currentFloorplan?.floor_name || '')
                }}
                className="p-1.5 text-slate-500 hover:text-slate-900 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800 rounded transition-colors opacity-0 group-hover:opacity-100"
                title="Rename floor"
              >
                <Edit3 className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setShowDeleteConfirm(true)}
                className="p-1.5 text-slate-500 hover:text-red-500 hover:bg-red-50 dark:text-slate-400 dark:hover:text-red-400 dark:hover:bg-red-400/10 rounded transition-colors opacity-0 group-hover:opacity-100"
                title="Delete floor"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
        
        {/* Floor Navigation */}
        <div className="flex items-center gap-3">
          <Link
            to={`/project/${projectId}/floor/${prevFloor?.id || ''}`}
            className={clsx(
              "p-2 rounded-lg transition-colors",
              prevFloor 
                ? "text-slate-400 hover:bg-slate-800 hover:text-white" 
                : "text-slate-700 cursor-not-allowed pointer-events-none"
            )}
            title={prevFloor ? `Previous: ${prevFloor.floor_name}` : 'No previous floor'}
          >
            <ChevronLeft className="w-5 h-5" />
          </Link>
          
          <div className="flex items-center gap-2 min-w-[120px] justify-center">
            <span className="text-slate-900 dark:text-white font-medium text-sm">
              {(currentIndex ?? 0) + 1}
            </span>
            <span className="text-slate-500 dark:text-slate-500 text-sm">
              of {currentProject?.floorplans?.length || 0}
            </span>
          </div>
          
          <Link
            to={`/project/${projectId}/floor/${nextFloor?.id || ''}`}
            className={clsx(
              "p-2 rounded-lg transition-colors",
              nextFloor 
                ? "text-slate-400 hover:bg-slate-800 hover:text-white" 
                : "text-slate-700 cursor-not-allowed pointer-events-none"
            )}
            title={nextFloor ? `Next: ${nextFloor.floor_name}` : 'No next floor'}
          >
            <ChevronRight className="w-5 h-5" />
          </Link>
        </div>
        
        <button
          onClick={handleMarkComplete}
          className="btn btn-primary text-sm"
        >
          <Check className="w-4 h-4 mr-1" />
          Mark Complete
        </button>
      </div>
      
      <div className="flex-1 flex overflow-hidden">
        {/* Toolbar */}
        <div className="w-14 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-700 flex flex-col items-center py-4 gap-2">
          <button
            onClick={() => setTool('select')}
            className={clsx(
              'p-3 rounded-lg transition-colors',
              tool === 'select' ? 'bg-sign-500 text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white'
            )}
            title="Select (V)"
          >
            <MousePointer className="w-5 h-5" />
          </button>
          
          <button
            onClick={() => setTool('draw')}
            className={clsx(
              'p-3 rounded-lg transition-colors',
              tool === 'draw' ? 'bg-sign-500 text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white'
            )}
            title="Draw Region (D)"
          >
            <Square className="w-5 h-5" />
          </button>
          
          <div className="h-px w-8 bg-slate-200 dark:bg-slate-700 my-2" />
          
          <button
            onClick={() => setScale(s => Math.min(s * 1.2, 5))}
            className="p-3 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white rounded-lg transition-colors"
            title="Zoom In"
          >
            <ZoomIn className="w-5 h-5" />
          </button>
          
          <button
            onClick={() => setScale(s => Math.max(s * 0.8, 0.1))}
            className="p-3 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white rounded-lg transition-colors"
            title="Zoom Out"
          >
            <ZoomOut className="w-5 h-5" />
          </button>
          
          <button
            onClick={() => { setScale(1); setOffset({ x: 0, y: 0 }) }}
            className="p-3 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white rounded-lg transition-colors"
            title="Reset View"
          >
            <Move className="w-5 h-5" />
          </button>
        </div>
        
        {/* Canvas Area */}
        <div 
          ref={containerRef}
          className="flex-1 relative overflow-hidden bg-slate-50 dark:bg-slate-900"
        >
          <canvas
            ref={canvasRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            className={clsx(
              'absolute inset-0',
              tool === 'draw' ? 'cursor-crosshair' : isPanning ? 'cursor-grabbing' : 'cursor-grab'
            )}
          />
          
          {!imageLoaded && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-8 h-8 border-2 border-sign-500/30 border-t-sign-500 rounded-full animate-spin" />
            </div>
          )}
          
          {/* Processing Overlay */}
          {(isDetectingShapes || isRunningOCR) && (
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-10">
              <div className="bg-slate-800 rounded-lg shadow-xl p-6 flex flex-col items-center gap-4 border border-slate-700">
                <Loader2 className="w-10 h-10 text-sign-500 animate-spin" />
                <div className="text-center">
                  <p className="text-white font-medium mb-1">
                    {isDetectingShapes ? 'Detecting Shapes...' : 'Running OCR...'}
                  </p>
                  <p className="text-slate-400 text-sm">
                    {isDetectingShapes 
                      ? 'Analyzing floor plan and identifying shapes' 
                      : 'Extracting text from detected shapes'}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
        
        {/* Right Panel */}
        <div className="w-80 bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 flex flex-col">
          {/* Actions */}
          <div className="p-4 border-b border-slate-200 dark:border-slate-700">
            <h3 className="font-medium text-slate-900 dark:text-white mb-3">Detection</h3>
            
            <div className="flex gap-2 mb-3">
              <button
                onClick={() => setShapeType('auto')}
                className={clsx(
                  'flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  shapeType === 'auto' ? 'bg-sign-500 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                )}
              >
                Auto
              </button>
              <button
                onClick={() => setShapeType('circle')}
                className={clsx(
                  'flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-1',
                  shapeType === 'circle' ? 'bg-sign-500 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                )}
              >
                <Circle className="w-4 h-4" />
              </button>
              <button
                onClick={() => setShapeType('rectangle')}
                className={clsx(
                  'flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-1',
                  shapeType === 'rectangle' ? 'bg-sign-500 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                )}
              >
                <Square className="w-4 h-4" />
              </button>
            </div>
            
            <div className="flex gap-2">
              <button
                onClick={handleDetectShapes}
                disabled={isDetectingShapes || isRunningOCR}
                className="btn btn-secondary flex-1 text-sm flex items-center justify-center gap-2"
              >
                {isDetectingShapes ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Detecting...
                  </>
                ) : (
                  <>
                    <Scan className="w-4 h-4" />
                    Detect Shapes
                  </>
                )}
              </button>
              
              <button
                onClick={handleRunOCR}
                disabled={isDetectingShapes || isRunningOCR || !currentFloorplan?.extracted_data?.length}
                className="btn btn-primary flex-1 text-sm flex items-center justify-center gap-2"
              >
                {isRunningOCR ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    <Type className="w-4 h-4" />
                    Run OCR
                  </>
                )}
              </button>
            </div>
          </div>
          
          {/* Selected Shape Info */}
          {selectedData && (
            <div className="p-4 border-b border-slate-200 dark:border-slate-700">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-medium text-slate-900 dark:text-white">Selected Shape</h3>
                <button
                  onClick={() => handleDeleteShape(selectedData.id)}
                  className="p-1.5 text-red-400 hover:bg-red-400/10 rounded transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
              
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">Type</span>
                  <span className="text-slate-900 dark:text-white capitalize">{selectedData.shape_type}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">Position</span>
                  <span className="text-slate-900 dark:text-white font-mono text-xs">
                    {selectedData.x}, {selectedData.y}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">Size</span>
                  <span className="text-slate-900 dark:text-white font-mono text-xs">
                    {selectedData.width} × {selectedData.height}
                  </span>
                </div>
                
                <div className="pt-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-slate-600 dark:text-slate-400">Extracted Text</span>
                    {editingText !== selectedData.id && (
                      <button
                        onClick={() => {
                          setEditingText(selectedData.id)
                          setEditText(selectedData.display_text || '')
                        }}
                        className="p-1 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
                      >
                        <Edit3 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  
                  {editingText === selectedData.id ? (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        className="input text-sm py-1.5"
                        autoFocus
                      />
                      <button
                        onClick={handleSaveText}
                        className="p-2 bg-emerald-500 text-white rounded-lg hover:bg-emerald-400"
                      >
                        <Check className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setEditingText(null)}
                        className="p-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <p className="text-slate-900 dark:text-white bg-slate-100 dark:bg-slate-800 rounded-lg p-2 font-mono text-xs">
                      {selectedData.display_text || <span className="text-slate-500">No text</span>}
                    </p>
                  )}
                  
                  {selectedData.confidence !== null && (
                    <p className="text-xs text-slate-500 mt-1">
                      Confidence: {Math.round((selectedData.confidence || 0) * 100)}%
                    </p>
                  )}
                </div>
                
                {/* Quantity Field */}
                <div className="pt-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-slate-600 dark:text-slate-400">Quantity</span>
                    {editingQuantity !== selectedData.id && (
                      <button
                        onClick={() => {
                          setEditingQuantity(selectedData.id)
                          setEditQuantity(String(selectedData.quantity || 1))
                        }}
                        className="p-1 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
                      >
                        <Edit3 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  
                  {editingQuantity === selectedData.id ? (
                    <div className="flex gap-2">
                      <input
                        type="number"
                        min="1"
                        value={editQuantity}
                        onChange={(e) => setEditQuantity(e.target.value)}
                        className="input text-sm py-1.5"
                        autoFocus
                      />
                      <button
                        onClick={handleSaveQuantity}
                        className="p-2 bg-emerald-500 text-white rounded-lg hover:bg-emerald-400"
                      >
                        <Check className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setEditingQuantity(null)}
                        className="p-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="text-slate-900 dark:text-white bg-slate-100 dark:bg-slate-800 rounded-lg px-3 py-2 font-mono text-xs">
                        {selectedData.quantity || 1}
                      </span>
                      {(selectedData.quantity || 1) > 1 && (
                        <span className="text-xs px-2 py-1 bg-sign-500/20 text-sign-400 rounded">
                          ×{selectedData.quantity}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
          
          {/* Extracted Data List */}
          <div className="flex-1 overflow-auto">
            <div className="p-4">
              <h3 className="font-medium text-slate-900 dark:text-white mb-3">
                Extracted Data ({currentFloorplan?.extracted_data?.length || 0})
              </h3>
              
              {currentFloorplan?.extracted_data?.length === 0 ? (
                <p className="text-slate-500 text-sm">
                  No data extracted yet. Use "Detect Shapes" to find shapes, then "Run OCR" to extract text.
                </p>
              ) : (
                <div className="space-y-2">
                  {currentFloorplan?.extracted_data?.map((data, index) => (
                    <motion.div
                      key={data.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: index * 0.02 }}
                      onClick={() => setSelectedShape(data.id)}
                      className={clsx(
                        'p-3 rounded-lg cursor-pointer transition-colors',
                        selectedShape === data.id 
                          ? 'bg-sign-500/20 border border-sign-500/50' 
                          : 'bg-slate-100 dark:bg-slate-800 border border-transparent hover:border-slate-300 dark:hover:border-slate-600'
                      )}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="w-6 h-6 bg-blueprint-100 dark:bg-blueprint-900 rounded text-blueprint-700 dark:text-blueprint-400 text-xs font-bold flex items-center justify-center">
                          {index + 1}
                        </span>
                        <span className="text-xs text-slate-600 dark:text-slate-400 capitalize">{data.shape_type}</span>
                        {data.is_manual && (
                          <span className="text-xs px-1.5 py-0.5 bg-sign-500/20 text-sign-400 rounded">
                            manual
                          </span>
                        )}
                        {(data.merged_count && data.merged_count > 1) && (
                          <span 
                            className="text-xs px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded font-semibold"
                            title={`${data.merged_count} detections merged`}
                          >
                            {data.merged_count} merged
                          </span>
                        )}
                        {(data.quantity || 1) > 1 && (
                          <span className="text-xs px-1.5 py-0.5 bg-emerald-500/20 text-emerald-400 rounded font-semibold">
                            ×{data.quantity}
                          </span>
                        )}
                      </div>
                      <p className="text-slate-900 dark:text-white text-sm font-mono truncate">
                        {data.display_text || <span className="text-slate-500">No text</span>}
                      </p>
                    </motion.div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      
      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white dark:bg-slate-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 border border-slate-200 dark:border-slate-700"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
                <Trash2 className="w-5 h-5 text-red-400" />
              </div>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Delete Floor</h3>
            </div>
            
            <p className="text-slate-700 dark:text-slate-300 mb-6">
              Are you sure you want to delete <span className="font-semibold text-slate-900 dark:text-white">{currentFloorplan?.floor_name}</span>? 
              This will permanently remove the floor and all its extracted data. This action cannot be undone.
            </p>
            
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="px-4 py-2 bg-slate-200 text-slate-700 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-300 rounded-lg dark:hover:bg-slate-600 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteFloor}
                className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-400 transition-colors flex items-center gap-2"
              >
                <Trash2 className="w-4 h-4" />
                Delete Floor
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  )
}

