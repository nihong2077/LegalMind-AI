'use client'

/**
 * 记忆详情栏（T2.4）
 * 展示选中记忆的完整信息，支持星标 / 编辑 / 归档 / 删除 / 来源跳转。
 */
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Archive,
  ArchiveRestore,
  Brain,
  Link2,
  Pencil,
  Star,
  Trash2,
} from 'lucide-react'
import { memoryTypeLabel } from '@/app/lib/memory'
import { useMemoryStore } from '@/store/useMemoryStore'
import { useCollabStore } from '@/store/useCollabStore'
import MemoryEditor from './MemoryEditor'

export default function MemoryDetail() {
  const router = useRouter()
  const items = useMemoryStore((s) => s.items)
  const selectedId = useMemoryStore((s) => s.selectedId)
  const toggleStar = useMemoryStore((s) => s.toggleStar)
  const deleteMemory = useMemoryStore((s) => s.deleteMemory)
  const updateMemory = useMemoryStore((s) => s.updateMemory)
  const selectConversation = useCollabStore((s) => s.selectConversation)

  const [editing, setEditing] = useState(false)

  const memory = items.find((m) => m.id === selectedId) || null

  if (!memory) {
    return (
      <main className="flex-1 h-screen flex flex-col items-center justify-center gap-3 bg-slate-50">
        <Brain size={40} className="text-slate-300" />
        <p className="text-sm text-slate-400">选择左侧记忆查看详情，或手动新增一条</p>
      </main>
    )
  }

  const handleSourceJump = async () => {
    if (!memory.source_conversation_id) return
    await selectConversation(memory.source_conversation_id)
    router.push('/messages')
  }

  const archived = memory.status === 'archived'

  return (
    <main className="flex-1 h-screen flex flex-col min-w-0 bg-slate-50 overflow-y-auto">
      <header className="h-14 px-5 flex items-center justify-between border-b border-slate-200 bg-white flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-lg bg-blue-100 text-blue-600 flex items-center justify-center flex-shrink-0">
            <Brain size={17} />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-800 truncate">
              {memory.summary || memoryTypeLabel(memory.memory_type)}
            </h2>
            <p className="text-[11px] text-slate-400">
              {memoryTypeLabel(memory.memory_type)} · {memory.scope === 'case' ? '案件记忆' : '用户记忆'}
              {archived ? ' · 已归档' : ''}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => toggleStar(memory.id)}
            className={`w-8 h-8 flex items-center justify-center rounded-lg transition-colors ${
              memory.starred
                ? 'text-amber-400 hover:bg-amber-50'
                : 'text-slate-400 hover:bg-slate-100'
            }`}
            title={memory.starred ? '取消星标' : '星标置顶'}
          >
            <Star size={16} className={memory.starred ? 'fill-amber-400' : ''} />
          </button>
          <button
            onClick={() => setEditing(true)}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
            title="编辑"
          >
            <Pencil size={16} />
          </button>
          <button
            onClick={() =>
              updateMemory(memory.id, { status: archived ? 'active' : 'archived' })
            }
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
            title={archived ? '恢复' : '归档'}
          >
            {archived ? <ArchiveRestore size={16} /> : <Archive size={16} />}
          </button>
          <button
            onClick={() => deleteMemory(memory.id)}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
            title="删除"
          >
            <Trash2 size={16} />
          </button>
        </div>
      </header>

      <div className="p-6 max-w-3xl space-y-4">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-semibold text-slate-500">记忆内容</h4>
            <div className="flex items-center gap-0.5" title={`重要性 ${memory.importance}/5`}>
              {[1, 2, 3, 4, 5].map((n) => (
                <Star
                  key={n}
                  size={13}
                  className={n <= memory.importance ? 'fill-amber-400 text-amber-400' : 'text-slate-200'}
                />
              ))}
            </div>
          </div>
          <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
            {memory.content}
          </p>
          {memory.summary && (
            <p className="text-xs text-slate-400 mt-3 pt-3 border-t border-slate-100">
              摘要：{memory.summary}
            </p>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-2">
          <h4 className="text-xs font-semibold text-slate-500 mb-1">来源与元信息</h4>
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400">来源会话</span>
            {memory.source_conversation_id ? (
              <button
                onClick={handleSourceJump}
                className="flex items-center gap-1 text-blue-600 hover:text-blue-700"
              >
                <Link2 size={12} /> 查看来源会话
              </button>
            ) : (
              <span className="text-slate-300">无（手动新增）</span>
            )}
          </div>
          {memory.case_id && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">关联案件</span>
              <span className="text-slate-500 font-mono text-[11px]">{memory.case_id}</span>
            </div>
          )}
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400">向量状态</span>
            <span className="text-slate-500">{memory.embedding_status}</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400">更新时间</span>
            <span className="text-slate-500">
              {memory.updated_at ? new Date(memory.updated_at).toLocaleString('zh-CN') : '-'}
            </span>
          </div>
        </div>
      </div>

      <MemoryEditor open={editing} onClose={() => setEditing(false)} initial={memory} />
    </main>
  )
}
