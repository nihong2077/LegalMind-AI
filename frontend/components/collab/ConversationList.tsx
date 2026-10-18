'use client'

/**
 * 会话列表（T1.8-M1）
 * 数据源：GET /api/conversations；direct/group 图标区分；支持标题搜索过滤。
 */
import { useMemo, useState } from 'react'
import { Loader2, MessagesSquare, Plus, Search, User, Users } from 'lucide-react'
import { useCollabStore } from '@/store/useCollabStore'
import { conversationTitle, relativeTime } from './format'

interface ConversationListProps {
  /** 打开建群向导（T1.8-M3 接入） */
  onNewConversation?: () => void
}

export default function ConversationList({ onNewConversation }: ConversationListProps) {
  const conversations = useCollabStore((s) => s.conversations)
  const agents = useCollabStore((s) => s.agents)
  const loading = useCollabStore((s) => s.loading)
  const error = useCollabStore((s) => s.error)
  const selectedId = useCollabStore((s) => s.selectedId)
  const selectConversation = useCollabStore((s) => s.selectConversation)
  const [keyword, setKeyword] = useState('')

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return conversations
    return conversations.filter((c) =>
      conversationTitle(c, agents).toLowerCase().includes(kw),
    )
  }, [conversations, agents, keyword])

  return (
    <section className="w-[300px] h-screen bg-white border-r border-slate-200 flex flex-col flex-shrink-0">
      <header className="h-14 px-4 flex items-center justify-between border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-800">消息</h2>
        <button
          onClick={onNewConversation}
          disabled={!onNewConversation}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-blue-600 hover:bg-blue-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-slate-500"
          title={onNewConversation ? '新建会话 / 建群' : '建群向导将在下一步接入'}
        >
          <Plus size={18} />
        </button>
      </header>

      <div className="p-3 border-b border-slate-100">
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索会话"
            className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && conversations.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center gap-3 text-slate-400">
            <Loader2 size={22} className="animate-spin" />
            <p className="text-xs">加载会话中...</p>
          </div>
        )}

        {!loading && error && (
          <div className="p-4 text-xs text-red-500">{error}</div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-slate-400 px-6 text-center">
            <MessagesSquare size={28} className="text-slate-300" />
            <p className="text-xs leading-relaxed">
              {conversations.length === 0
                ? '还没有会话，点右上角 + 新建单聊或群聊'
                : '没有匹配的会话'}
            </p>
          </div>
        )}

        {filtered.map((conv) => {
          const active = conv.id === selectedId
          const title = conversationTitle(conv, agents)
          const GroupIcon = conv.type === 'group' ? Users : User
          return (
            <button
              key={conv.id}
              onClick={() => selectConversation(conv.id)}
              className={`w-full flex items-center gap-3 px-3 py-3 text-left border-b border-slate-50 transition-colors ${
                active ? 'bg-blue-50/70' : 'hover:bg-slate-50'
              }`}
            >
              <div
                className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                  conv.type === 'group'
                    ? 'bg-blue-100 text-blue-600'
                    : 'bg-slate-100 text-slate-500'
                }`}
              >
                <GroupIcon size={18} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-sm truncate ${
                      active ? 'font-semibold text-blue-700' : 'font-medium text-slate-800'
                    }`}
                  >
                    {title}
                  </span>
                  {conv.type === 'group' && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-500 flex-shrink-0">
                      {conv.members.length}人
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between gap-2 mt-0.5">
                  <span className="text-[11px] text-slate-400 truncate">
                    {conv.case_type ? conv.case_type : conv.type === 'direct' ? '单聊' : '群聊'}
                  </span>
                  <span className="text-[11px] text-slate-400 flex-shrink-0">
                    {relativeTime(conv.updated_at || conv.created_at)}
                  </span>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
