'use client'

/**
 * 聊天区（T1.8-M1：外壳 + 会话头）
 * 消息气泡 / SSE 流式 / 交互卡片在 M2 接入；此处仅呈现选中会话的头部信息。
 */
import { PanelRight, MessagesSquare, Users, User } from 'lucide-react'
import { useCollabStore } from '@/store/useCollabStore'
import Avatar from './Avatar'
import ConversationView from './ConversationView'
import { conversationTitle } from './format'

export default function ChatArea() {
  const conversations = useCollabStore((s) => s.conversations)
  const agents = useCollabStore((s) => s.agents)
  const selectedId = useCollabStore((s) => s.selectedId)
  const rightRailOpen = useCollabStore((s) => s.rightRailOpen)
  const toggleRightRail = useCollabStore((s) => s.toggleRightRail)

  const conversation = conversations.find((c) => c.id === selectedId) || null

  if (!conversation) {
    return (
      <main className="flex-1 h-screen flex flex-col items-center justify-center gap-3 bg-slate-50">
        <MessagesSquare size={40} className="text-slate-300" />
        <p className="text-sm text-slate-400">选择左侧会话，或新建单聊 / 群聊</p>
      </main>
    )
  }

  const title = conversationTitle(conversation, agents)
  const TypeIcon = conversation.type === 'group' ? Users : User
  const members = conversation.members
  const shown = members.slice(0, 6)

  return (
    <main className="flex-1 h-screen flex flex-col min-w-0 bg-slate-50">
      <header className="h-14 px-5 flex items-center justify-between border-b border-slate-200 bg-white flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
              conversation.type === 'group'
                ? 'bg-blue-100 text-blue-600'
                : 'bg-slate-100 text-slate-500'
            }`}
          >
            <TypeIcon size={17} />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-800 truncate">{title}</h2>
            <p className="text-[11px] text-slate-400">
              {conversation.type === 'group'
                ? `${members.length} 位成员${conversation.case_type ? ` · ${conversation.case_type}` : ''}`
                : '单聊'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {conversation.type === 'group' && shown.length > 0 && (
            <div className="hidden lg:flex items-center -space-x-2">
              {shown.map((m) => (
                <Avatar
                  key={m.agent_id}
                  name={m.name || m.agent_id}
                  avatar={m.avatar}
                  seed={m.agent_id}
                  size={26}
                  className="ring-2 ring-white"
                />
              ))}
              {members.length > shown.length && (
                <div className="w-[26px] h-[26px] rounded-full bg-slate-200 ring-2 ring-white flex items-center justify-center text-[10px] text-slate-500">
                  +{members.length - shown.length}
                </div>
              )}
            </div>
          )}
          <button
            onClick={toggleRightRail}
            title={rightRailOpen ? '收起侧栏' : '展开侧栏'}
            className={`w-8 h-8 flex items-center justify-center rounded-lg transition-colors ${
              rightRailOpen ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            <PanelRight size={17} />
          </button>
        </div>
      </header>

      <ConversationView conversation={conversation} agents={agents} key={conversation.id} />
    </main>
  )
}
