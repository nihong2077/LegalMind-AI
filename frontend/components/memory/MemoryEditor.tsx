'use client'

/**
 * 记忆新增 / 编辑弹窗（T2.4）
 * initial 为空表示新增；否则为编辑（PATCH）。
 */
import { useEffect, useState } from 'react'
import { Loader2, X } from 'lucide-react'
import { CreateMemoryBody, MEMORY_TYPE_TABS, MemoryRecord } from '@/app/lib/memory'
import { ApiError } from '@/app/lib/api'
import { useMemoryStore } from '@/store/useMemoryStore'

interface MemoryEditorProps {
  open: boolean
  onClose: () => void
  /** 传入则为编辑，null/undefined 为新增 */
  initial?: MemoryRecord | null
}

const TYPE_OPTIONS = MEMORY_TYPE_TABS.filter((t) => t.key !== 'all')

export default function MemoryEditor({ open, onClose, initial }: MemoryEditorProps) {
  const createMemory = useMemoryStore((s) => s.createMemory)
  const updateMemory = useMemoryStore((s) => s.updateMemory)

  const [memoryType, setMemoryType] = useState('fact')
  const [content, setContent] = useState('')
  const [summary, setSummary] = useState('')
  const [importance, setImportance] = useState(3)
  const [starred, setStarred] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setMemoryType(initial?.memory_type || 'fact')
    setContent(initial?.content || '')
    setSummary(initial?.summary || '')
    setImportance(initial?.importance ?? 3)
    setStarred(initial?.starred ?? false)
  }, [open, initial])

  if (!open) return null

  const handleSave = async () => {
    if (!content.trim()) {
      setError('记忆内容不能为空')
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (initial) {
        await updateMemory(initial.id, {
          memory_type: memoryType,
          content: content.trim(),
          summary: summary.trim() || null,
          importance,
          starred,
        })
      } else {
        const body: CreateMemoryBody = {
          memory_type: memoryType,
          content: content.trim(),
          summary: summary.trim() || null,
          importance,
          starred,
        }
        await createMemory(body)
      }
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-xl overflow-hidden">
        <header className="px-5 h-14 flex items-center justify-between border-b border-slate-100">
          <h3 className="text-sm font-semibold text-slate-800">
            {initial ? '编辑记忆' : '新增记忆'}
          </h3>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 transition-colors"
          >
            <X size={16} />
          </button>
        </header>

        <div className="p-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1.5">分类</label>
            <select
              value={memoryType}
              onChange={(e) => setMemoryType(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 focus:outline-none focus:border-blue-400"
            >
              {TYPE_OPTIONS.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1.5">内容</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              placeholder="例如：用户希望在 2026 年 11 月前拿到可提交仲裁的证据清单"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 resize-none"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1.5">
              摘要（可选）
            </label>
            <input
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="一句话概括，便于列表展示"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400"
            />
          </div>

          <div className="flex items-center gap-6">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1.5">重要性</label>
              <div className="flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    onClick={() => setImportance(n)}
                    className={`text-lg leading-none transition-colors ${
                      n <= importance ? 'text-amber-400' : 'text-slate-200'
                    }`}
                    title={`${n} 星`}
                  >
                    ★
                  </button>
                ))}
              </div>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
              <input
                type="checkbox"
                checked={starred}
                onChange={(e) => setStarred(e.target.checked)}
                className="accent-amber-400"
              />
              星标置顶
            </label>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        <footer className="px-5 py-3 border-t border-slate-100 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-xs text-slate-600 hover:bg-slate-100 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 text-white text-xs hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 size={13} className="animate-spin" />}
            保存
          </button>
        </footer>
      </div>
    </div>
  )
}
