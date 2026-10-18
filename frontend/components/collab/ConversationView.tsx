'use client'

/**
 * 会话消息视图（T1.8-M2）
 *
 * - 打开时拉历史（store.open）+ 建立 SSE 流；卸载/切换会话时关流。
 * - 单聊（direct）保持简单：气泡 + typing + 输入框。
 * - 群聊额外渲染：相位条（status）、交互卡片（interaction_required）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Loader2, RotateCcw, Search, Send, Undo2 } from 'lucide-react'
import { AgentInfo, Conversation, setMyRole } from '@/app/lib/collab'
import { useCollabStore } from '@/store/useCollabStore'
import { useCollabStreamStore } from '@/store/useCollabStreamStore'
import InteractionCard from './InteractionCard'
import MessageBubble from './MessageBubble'

interface ConversationViewProps {
  conversation: Conversation
  agents: AgentInfo[]
}

export default function ConversationView({ conversation, agents }: ConversationViewProps) {
  const messages = useCollabStreamStore((s) => s.messages)
  const streams = useCollabStreamStore((s) => s.streams)
  const toolRuns = useCollabStreamStore((s) => s.toolRuns)
  const phase = useCollabStreamStore((s) => s.phase)
  const phaseText = useCollabStreamStore((s) => s.phaseText)
  const pending = useCollabStreamStore((s) => s.pending)
  const error = useCollabStreamStore((s) => s.error)
  const sending = useCollabStreamStore((s) => s.sending)
  const loadingHistory = useCollabStreamStore((s) => s.loadingHistory)
  const open = useCollabStreamStore((s) => s.open)
  const close = useCollabStreamStore((s) => s.close)
  const send = useCollabStreamStore((s) => s.send)
  const handBack = useCollabStreamStore((s) => s.handBack)
  const conclude = useCollabStreamStore((s) => s.conclude)
  const retryLast = useCollabStreamStore((s) => s.retryLast)
  const upsertConversation = useCollabStore((s) => s.upsertConversation)

  const isGroup = conversation.type === 'group'
  const [input, setInput] = useState('')
  const [roleBusy, setRoleBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    open(conversation.id)
    return () => close()
  }, [conversation.id, open, close])

  /** 当前用户扮演的 Agent 名称（仅群聊） */
  const playingName = useMemo(() => {
    if (!conversation.my_role) return null
    const m = conversation.members.find((x) => x.agent_id === conversation.my_role)
    return m?.name || conversation.my_role
  }, [conversation.my_role, conversation.members])

  /** 「交还给 AI」：挂起接管 → 续跑让 AI 代答；否则直接清空跨轮扮演标志 */
  const handleReleaseRole = async () => {
    if (roleBusy) return
    setRoleBusy(true)
    try {
      if (pending?.type === 'takeover') {
        await handBack()
      } else {
        const updated = await setMyRole(conversation.id, null)
        upsertConversation(updated)
      }
    } catch {
      // 失败静默：状态仍以服务端为准，下次刷新回归
    } finally {
      setRoleBusy(false)
    }
  }

  const agentById = useMemo(() => {
    const map = new Map<string, { avatar?: string | null }>()
    conversation.members.forEach((m) => map.set(m.agent_id, { avatar: m.avatar }))
    agents.forEach((a) => map.set(a.agent_id, { avatar: a.avatar }))
    return map
  }, [conversation.members, agents])

  const streamKeys = Object.keys(streams)
  const typing = streamKeys.length > 0 || phase === 'turn_running'

  // 新内容自动滚到底部
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, streams, pending, phaseText, error])

  const handleSend = () => {
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    void send(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const placeholder =
    pending?.type === 'takeover'
      ? `以「${pending.agent_name || '该角色'}」身份发言…`
      : pending
        ? '输入你的回答…'
        : '输入消息，Enter 发送，Shift+Enter 换行'

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* ⓪ 扮演角标（仅群聊 + 正在扮演） */}
      {isGroup && playingName && (
        <div className="px-4 py-1.5 border-b border-amber-100 bg-amber-50 flex items-center justify-between gap-3 flex-shrink-0">
          <span className="text-[11px] text-amber-700">你正在扮演「{playingName}」</span>
          <button
            onClick={() => void handleReleaseRole()}
            disabled={roleBusy}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-amber-700 border border-amber-300 hover:bg-amber-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {roleBusy ? <Loader2 size={11} className="animate-spin" /> : <Undo2 size={11} />}
            交还给 AI
          </button>
        </div>
      )}

      {/* ① 相位条（仅群聊） */}
      {isGroup && phaseText && (
        <div className="px-4 py-1.5 border-b border-blue-100 bg-blue-50 flex items-center gap-2 flex-shrink-0">
          <Loader2 size={12} className="animate-spin text-blue-500" />
          <span className="text-[11px] text-blue-600">{phaseText}</span>
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {loadingHistory && (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-slate-400">
            <Loader2 size={20} className="animate-spin" />
            <p className="text-xs">加载消息中…</p>
          </div>
        )}

        {!loadingHistory && messages.length === 0 && streamKeys.length === 0 && (
          <div className="h-full flex items-center justify-center">
            <p className="text-xs text-slate-400">还没有消息，开始你的第一次发言吧</p>
          </div>
        )}

        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            senderType={m.sender_type}
            senderName={m.sender_name || ''}
            content={m.content}
            msgType={m.msg_type}
            metadata={m.metadata}
            avatar={m.sender_type === 'user' ? null : agentById.get(m.sender_id)?.avatar ?? null}
            seed={m.sender_id}
          />
        ))}

        {Object.entries(streams).map(([mid, bubble]) => (
          <MessageBubble
            key={`stream-${mid}`}
            senderType={bubble.sender_type}
            senderName={bubble.sender_name}
            content={bubble.content}
            avatar={agentById.get(bubble.sender_id)?.avatar ?? null}
            seed={bubble.sender_id}
            streaming
          />
        ))}

        {typing && !streamKeys.length && (
          <div className="flex items-center gap-2 text-slate-400 pl-1">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce" />
            <span
              className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce"
              style={{ animationDelay: '0.15s' }}
            />
            <span
              className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce"
              style={{ animationDelay: '0.3s' }}
            />
            <span className="text-[11px]">正在思考…</span>
          </div>
        )}

        {/* ③ 工具辐条进度（法规/类案检索） */}
        {isGroup &&
          toolRuns.map((t) => (
            <div
              key={`tool-${t.agent_id}`}
              className="flex items-center gap-2 text-[11px] text-slate-500 pl-1"
            >
              {t.status === 'running' ? (
                <Loader2 size={11} className="animate-spin text-blue-500" />
              ) : (
                <Search size={11} className="text-slate-400" />
              )}
              <span>
                {t.agent_name}
                {t.status === 'running'
                  ? ` 正在检索「${t.query}」…`
                  : t.status === 'error'
                    ? ' 检索失败，已跳过'
                    : ` 检索到 ${t.result_count ?? 0} 条${
                        t.tool === 'law' ? '法规' : t.tool === 'judge' ? '类案' : '资料'
                      }`}
              </span>
            </div>
          ))}

        {/* ② 交互卡片（仅群聊） */}
        {isGroup && pending && (
          <InteractionCard
            pending={pending}
            onHandBack={handBack}
            onConclude={() => void conclude()}
            disabled={sending}
          />
        )}
      </div>

      {/* 错误条 */}
      {error && (
        <div className="mx-4 mt-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 flex items-center justify-between gap-3 flex-shrink-0">
          <span className="flex items-center gap-1.5 text-xs text-red-600 min-w-0">
            <AlertCircle size={13} className="flex-shrink-0" />
            <span className="truncate">{error.message}</span>
          </span>
          {error.retryable && (
            <button
              onClick={() => void retryLast()}
              disabled={sending}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs text-red-600 hover:bg-red-100 transition-colors flex-shrink-0 disabled:opacity-40"
            >
              <RotateCcw size={12} />
              重试
            </button>
          )}
        </div>
      )}

      {/* 底部输入区 */}
      <div className="border-t border-slate-200 bg-white p-3 flex-shrink-0">
        {pending?.type === 'takeover' && (
          <p className="mb-2 text-[11px] text-amber-600">
            你正在以「{pending.agent_name || '该角色'}」身份发言
          </p>
        )}
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder={placeholder}
            className="input-field resize-none flex-1 text-sm"
          />
          <button
            onClick={handleSend}
            disabled={sending || !input.trim()}
            className="gold-btn-sm flex items-center gap-1.5 h-[46px] flex-shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            发送
          </button>
        </div>
      </div>
    </div>
  )
}
