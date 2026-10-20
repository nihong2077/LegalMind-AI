'use client'

/**
 * 记忆列表栏（T2.4）
 * 顶部分类 Tab + 星标/归档过滤 + 关键词搜索；底部召回总开关。
 */
import { useEffect } from 'react'
import { Archive, Brain, Loader2, Plus, Search, Sparkles, Star } from 'lucide-react'
import { MEMORY_TYPE_TABS, memoryTypeLabel } from '@/app/lib/memory'
import { useMemoryStore } from '@/store/useMemoryStore'
import { relativeTime } from '@/components/collab/format'

interface MemoryListProps {
  onNewMemory: () => void
}

export default function MemoryList({ onNewMemory }: MemoryListProps) {
  const items = useMemoryStore((s) => s.items)
  const total = useMemoryStore((s) => s.total)
  const loading = useMemoryStore((s) => s.loading)
  const error = useMemoryStore((s) => s.error)
  const filters = useMemoryStore((s) => s.filters)
  const selectedId = useMemoryStore((s) => s.selectedId)
  const select = useMemoryStore((s) => s.select)
  const setFilters = useMemoryStore((s) => s.setFilters)
  const enabled = useMemoryStore((s) => s.enabled)
  const setEnabled = useMemoryStore((s) => s.setEnabled)
  const fetchMemories = useMemoryStore((s) => s.fetchMemories)

  useEffect(() => {
    fetchMemories()
  }, [fetchMemories])

  return (
    <section className="w-[300px] h-screen bg-white border-r border-slate-200 flex flex-col flex-shrink-0">
      <header className="h-14 px-4 flex items-center justify-between border-b border-slate-200">
        <div className="flex items-center gap-2">
          <Brain size={17} className="text-blue-500" />
          <h2 className="text-base font-semibold text-slate-800">记忆</h2>
          <span className="text-[11px] text-slate-400">{total} 条</span>
        </div>
        <button
          onClick={onNewMemory}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-blue-600 hover:bg-blue-50 transition-colors"
          title="手动新增记忆"
        >
          <Plus size={18} />
        </button>
      </header>

      {/* 召回总开关 */}
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <Sparkles size={14} className="text-blue-400 flex-shrink-0" />
          <div className="min-w-0">
            <p className="text-xs font-medium text-slate-700">自动记忆</p>
            <p className="text-[10px] text-slate-400">关闭后不再自动记录与召回</p>
          </div>
        </div>
        <button
          role="switch"
          aria-checked={enabled}
          onClick={() => setEnabled(!enabled)}
          className={`w-9 h-5 rounded-full flex items-center px-0.5 flex-shrink-0 transition-colors ${
            enabled ? 'bg-blue-500' : 'bg-slate-300'
          }`}
          title={enabled ? '已开启' : '已关闭'}
        >
          <span
            className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${
              enabled ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      {/* 分类 Tab */}
      <div className="px-3 pt-3 flex gap-1 overflow-x-auto border-b border-slate-100 pb-2">
        {MEMORY_TYPE_TABS.map((tab) => {
          const active = filters.memoryType === tab.key
          return (
            <button
              key={tab.key}
              onClick={() => setFilters({ memoryType: tab.key })}
              className={`px-2.5 py-1 rounded-full text-[11px] whitespace-nowrap transition-colors ${
                active
                  ? 'bg-blue-100 text-blue-700 font-medium'
                  : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* 搜索 + 过滤 */}
      <div className="p-3 space-y-2 border-b border-slate-100">
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={filters.query}
            onChange={(e) => setFilters({ query: e.target.value })}
            placeholder="搜索记忆内容"
            className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
          />
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setFilters({ starredOnly: !filters.starredOnly })}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] transition-colors ${
              filters.starredOnly
                ? 'bg-amber-100 text-amber-600 font-medium'
                : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            <Star size={12} className={filters.starredOnly ? 'fill-amber-400 text-amber-400' : ''} />
            星标
          </button>
          <button
            onClick={() =>
              setFilters({ status: filters.status === 'active' ? 'archived' : 'active' })
            }
            className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] transition-colors ${
              filters.status === 'archived'
                ? 'bg-slate-200 text-slate-700 font-medium'
                : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            <Archive size={12} />
            {filters.status === 'archived' ? '已归档' : '归档'}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && items.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center gap-3 text-slate-400">
            <Loader2 size={22} className="animate-spin" />
            <p className="text-xs">加载记忆中...</p>
          </div>
        )}

        {!loading && error && <div className="p-4 text-xs text-red-500">{error}</div>}

        {!loading && !error && items.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-slate-400 px-6 text-center">
            <Brain size={28} className="text-slate-300" />
            <p className="text-xs leading-relaxed">
              暂无记忆，多轮对话后系统会自动沉淀，也可点右上角 + 手动新增
            </p>
          </div>
        )}

        {items.map((m) => {
          const active = m.id === selectedId
          return (
            <button
              key={m.id}
              onClick={() => select(m.id)}
              className={`w-full text-left px-4 py-3 border-b border-slate-50 transition-colors ${
                active ? 'bg-blue-50/70' : 'hover:bg-slate-50'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                {m.starred && <Star size={11} className="fill-amber-400 text-amber-400 flex-shrink-0" />}
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-500 flex-shrink-0">
                  {memoryTypeLabel(m.memory_type)}
                </span>
                <span className="text-[10px] text-slate-300 flex-1 text-right">
                  {relativeTime(m.updated_at || m.created_at)}
                </span>
              </div>
              <p className={`text-xs line-clamp-2 ${active ? 'text-blue-800' : 'text-slate-700'}`}>
                {m.summary || m.content}
              </p>
            </button>
          )
        })}
      </div>
    </section>
  )
}
