'use client'

/**
 * 「引用并新建协同群」弹窗（T3.2）
 * 选案情模板 → 建群并把引用内容作为首条发言送出（由此起首轮协同）。
 */
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Check, Loader2, MessagesSquare, X } from 'lucide-react'
import { ApiError } from '@/app/lib/api'
import { TemplateCard, createConversation, sendCollabMessage } from '@/app/lib/collab'
import { SearchResult, resultToForwardText } from '@/app/lib/search'
import { useCollabStore } from '@/store/useCollabStore'

interface NewGroupFromQuoteDialogProps {
  result: SearchResult | null
  onClose: () => void
}

function errText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return '创建失败'
}

export default function NewGroupFromQuoteDialog({ result, onClose }: NewGroupFromQuoteDialogProps) {
  const router = useRouter()
  const templates = useCollabStore((s) => s.templates)
  const catalogLoaded = useCollabStore((s) => s.catalogLoaded)
  const fetchCatalog = useCollabStore((s) => s.fetchCatalog)
  const upsertConversation = useCollabStore((s) => s.upsertConversation)
  const selectConversation = useCollabStore((s) => s.selectConversation)

  const [template, setTemplate] = useState<TemplateCard | null>(null)
  const [title, setTitle] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!result) return
    setTemplate(null)
    setTitle('')
    setSubmitting(false)
    setError(null)
    if (!catalogLoaded) fetchCatalog()
  }, [result, catalogLoaded, fetchCatalog])

  if (!result) return null

  const submit = async () => {
    if (!template) return
    setSubmitting(true)
    setError(null)
    try {
      const conv = await createConversation({
        type: 'group',
        template_id: template.case_type,
        title: title.trim() || undefined,
      })
      // 引用内容作为首条发言 → 起首轮协同
      await sendCollabMessage(conv.id, { content: resultToForwardText(result) })
      upsertConversation(conv)
      await selectConversation(conv.id)
      onClose()
      router.push('/messages')
    } catch (e) {
      setError(errText(e))
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg mx-4 bg-white rounded-2xl shadow-xl flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="h-14 px-5 flex items-center justify-between border-b border-slate-200 flex-shrink-0">
          <h2 className="text-sm font-semibold text-slate-800">引用并新建协同群</h2>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* 引用内容预览 */}
          <div className="p-3 rounded-xl bg-blue-50 border border-blue-100">
            <p className="text-[11px] text-blue-700 font-medium mb-1">将作为群的起始案情</p>
            <p className="text-xs text-slate-600 line-clamp-3 whitespace-pre-wrap">
              {resultToForwardText(result)}
            </p>
          </div>

          <div>
            <p className="text-xs font-medium text-slate-500 mb-2">选择案情模板</p>
            <div className="space-y-2">
              {templates
                .filter((t) => t.enabled !== false)
                .map((t) => {
                  const active = template?.case_type === t.case_type
                  return (
                    <button
                      key={t.case_type}
                      onClick={() => setTemplate(t)}
                      className={`w-full flex items-start gap-3 p-3 rounded-xl border transition-colors text-left ${
                        active
                          ? 'border-blue-500 bg-blue-50/60'
                          : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <div className="w-9 h-9 rounded-lg bg-blue-100 text-blue-600 flex items-center justify-center flex-shrink-0">
                        <MessagesSquare size={16} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <span className="text-sm font-medium text-slate-800">{t.name}</span>
                        <span className="ml-2 text-[10px] text-slate-400">
                          {(t.roster_summary || []).length} 位成员
                        </span>
                        {t.description && (
                          <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-2">{t.description}</p>
                        )}
                      </div>
                      {active && <Check size={18} className="text-blue-600 flex-shrink-0 mt-1" />}
                    </button>
                  )
                })}
              {templates.length === 0 && (
                <p className="text-center text-xs text-slate-400 py-6">模板加载中或暂无可用模板</p>
              )}
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-slate-500 mb-2">群名称（可选）</p>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={template?.name || '协同群聊'}
              className="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
            />
          </div>

          {error && (
            <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <footer className="px-5 py-3 border-t border-slate-200 flex items-center justify-end gap-2 flex-shrink-0">
          <button
            onClick={onClose}
            className="h-9 px-4 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors"
          >
            取消
          </button>
          <button
            onClick={submit}
            disabled={!template || submitting}
            className="h-9 px-4 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 transition-colors"
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            创建并开始协同
          </button>
        </footer>
      </div>
    </div>
  )
}
