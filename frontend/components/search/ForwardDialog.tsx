'use client'

/**
 * 「转发到…」弹窗（T3.2）
 * 选择已有会话，把结果作为上下文卡片转发进去（后端不触发轮次）。
 */
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2, MessagesSquare, User, Users, X } from 'lucide-react'
import { ApiError } from '@/app/lib/api'
import { Conversation, listConversations } from '@/app/lib/collab'
import {
  SearchResult,
  forwardToConversation,
  resultCardType,
  resultToCitation,
  resultToForwardText,
} from '@/app/lib/search'
import { useCollabStore } from '@/store/useCollabStore'

interface ForwardDialogProps {
  result: SearchResult | null
  onClose: () => void
}

function errText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return '转发失败'
}

export default function ForwardDialog({ result, onClose }: ForwardDialogProps) {
  const router = useRouter()
  const selectConversation = useCollabStore((s) => s.selectConversation)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [doneId, setDoneId] = useState<string | null>(null)

  useEffect(() => {
    if (!result) return
    setDoneId(null)
    setError(null)
    setLoading(true)
    let alive = true
    listConversations('active')
      .then((all) => {
        if (alive) setConversations(all)
      })
      .catch((e) => {
        if (alive) setError(errText(e))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [result])

  if (!result) return null

  const handleForward = async (conv: Conversation) => {
    setSending(true)
    setError(null)
    try {
      await forwardToConversation(conv.id, {
        card_type: resultCardType(result),
        citations: [resultToCitation(result)],
        content: resultToForwardText(result),
      })
      setDoneId(conv.id)
    } catch (e) {
      setError(errText(e))
    } finally {
      setSending(false)
    }
  }

  const openConversation = async (id: string) => {
    await selectConversation(id)
    onClose()
    router.push('/messages')
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md mx-4 bg-white rounded-2xl shadow-xl flex flex-col max-h-[70vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="h-14 px-5 flex items-center justify-between border-b border-slate-200 flex-shrink-0">
          <h2 className="text-sm font-semibold text-slate-800">转发到…</h2>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <div className="mb-3 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          {loading && (
            <div className="flex items-center justify-center py-10 text-slate-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          )}

          {!loading && conversations.length === 0 && (
            <p className="text-center text-xs text-slate-400 py-10">暂无会话，请先在消息中心新建会话</p>
          )}

          <div className="space-y-1.5">
            {!loading &&
              conversations.map((c) => {
                const done = doneId === c.id
                return (
                  <div
                    key={c.id}
                    className="flex items-center gap-3 p-3 rounded-xl border border-slate-200"
                  >
                    <div
                      className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        c.type === 'group' ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-500'
                      }`}
                    >
                      {c.type === 'group' ? <Users size={16} /> : <User size={16} />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-slate-800 truncate">
                        {c.title || (c.type === 'group' ? '协同群聊' : '单聊')}
                      </p>
                      <p className="text-[10px] text-slate-400">
                        {c.type === 'group' ? `${c.members?.length ?? 0} 位成员` : '单聊'}
                      </p>
                    </div>
                    {done ? (
                      <button
                        onClick={() => openConversation(c.id)}
                        className="px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-600 text-xs hover:bg-emerald-100 transition-colors"
                      >
                        已发送 · 查看
                      </button>
                    ) : (
                      <button
                        onClick={() => handleForward(c)}
                        disabled={sending}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs hover:bg-blue-700 disabled:opacity-40 transition-colors"
                      >
                        {sending && <Loader2 size={12} className="animate-spin" />}
                        转发
                      </button>
                    )}
                  </div>
                )
              })}
          </div>
        </div>

        <footer className="px-5 py-3 border-t border-slate-200 flex items-center gap-2 text-[11px] text-slate-400 flex-shrink-0">
          <MessagesSquare size={12} />
          转发仅作为上下文卡片落入会话，不会立即触发 AI 发言。
        </footer>
      </div>
    </div>
  )
}
