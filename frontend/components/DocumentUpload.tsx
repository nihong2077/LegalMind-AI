'use client'

import { Upload, FileText, CheckCircle, AlertCircle, Clock } from 'lucide-react'
import { useState, useRef } from 'react'
import { motion } from 'framer-motion'

interface DocFile {
  id: string
  name: string
  size: string
  status: 'uploading' | 'analyzing' | 'ready' | 'error'
  type: string
}

export default function DocumentUpload() {
  const [files, setFiles] = useState<DocFile[]>([])
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFiles = (fileList: FileList | null) => {
    if (!fileList) return
    const newFiles: DocFile[] = Array.from(fileList).map((f) => ({
      id: Date.now().toString() + Math.random().toString(36).slice(2),
      name: f.name,
      size: (f.size / 1024).toFixed(1) + ' KB',
      status: 'uploading' as const,
      type: f.name.split('.').pop()?.toUpperCase() || 'FILE',
    }))
    setFiles((prev) => [...prev, ...newFiles])

    newFiles.forEach((f) => {
      setTimeout(() => {
        setFiles((prev) =>
          prev.map((item) => (item.id === f.id ? { ...item, status: 'analyzing' as const } : item))
        )
      }, 1500)
      setTimeout(() => {
        setFiles((prev) =>
          prev.map((item) => (item.id === f.id ? { ...item, status: 'ready' as const } : item))
        )
      }, 4000)
    })
  }

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true)
    else if (e.type === 'dragleave') setDragActive(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    handleFiles(e.dataTransfer.files)
  }

  const statusIcon = (status: DocFile['status']) => {
    switch (status) {
      case 'uploading':
      case 'analyzing':
        return <Clock size={14} className="text-gold-400 animate-pulse" />
      case 'ready':
        return <CheckCircle size={14} className="text-green-400" />
      case 'error':
        return <AlertCircle size={14} className="text-red-400" />
    }
  }

  const statusText = (status: DocFile['status']) => {
    switch (status) {
      case 'uploading': return '上传中...'
      case 'analyzing': return 'AI 分析中...'
      case 'ready': return '分析完成'
      case 'error': return '分析失败'
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gold-200 mb-1">文档智能分析</h2>
        <p className="text-sm text-gold-200/50">上传法律文书，AI 自动提取关键条款与风险点</p>
      </div>

      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`glass-card-static p-10 cursor-pointer text-center transition-all duration-300
                    ${dragActive ? 'border-gold-400/50 bg-gold-400/5' : 'hover:border-gold-400/30'}`}
      >
        <div className="w-16 h-16 mx-auto rounded-2xl bg-gold-400/10 flex items-center justify-center mb-4">
          <Upload size={28} className="text-gold-400" />
        </div>
        <p className="text-gold-200 mb-1">拖拽文件到此处，或点击上传</p>
        <p className="text-xs text-gold-200/40">支持 PDF、DOCX、TXT 格式，单文件最大 10MB</p>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          multiple
          accept=".pdf,.docx,.txt"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gold-200/70">已上传文件</h3>
          {files.map((f) => (
            <motion.div
              key={f.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className="glass-card-static p-4 flex items-center gap-4"
            >
              <div className="w-10 h-10 rounded-lg bg-gold-400/10 flex items-center justify-center flex-shrink-0">
                <FileText size={18} className="text-gold-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gold-200 truncate">{f.name}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-gold-200/30">{f.size}</span>
                  <span className="text-[10px] text-gold-200/30">·</span>
                  <span className="text-[10px] text-gold-200/30">{f.type}</span>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                {statusIcon(f.status)}
                <span className="text-xs text-gold-200/50">{statusText(f.status)}</span>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  )
}
