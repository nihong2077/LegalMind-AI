'use client'

/**
 * 搜索结果区（T3.2）
 * 顶部 Tab（全部/法规/类案/我的记忆/会话记录）+ 结果列表；
 * 每条结果可「转发到…」与「引用并新建协同群」，会话记录额外可「打开会话」。
 */
import { useMemo } from 'react'
import {
  Brain,
  ExternalLink,
  Gavel,
  Loader2,
  MessagesSquare,
  Scale,
  Search,
  Share2,
  Sparkles,
} from 'lucide-react'
import {
  MemoryResult,
  MessageResult,
  SearchResult,
  SearchTab,
  SEARCH_TABS,
  resultBody,
  resultTitle,
} from '@/app/lib/search'
import { relativeTime } from '@/components/collab/format'
import { useSearchStore } from '@/store/useSearchStore'

interface SearchResultsProps {
  onForward: (r: SearchResult) => void
  onQuote: (r: SearchResult) => void
  onOpenMessage: (r: MessageResult) => void
}

const DOT: Record<string, string> = {
  law: 'w-1.5 h-1.5 rounded-full bg-blue-400',
  judge: 'w-1.5 h-1.5 rounded-full bg-emerald-400',
  memory: 'w-1.5 h-1.5 rounded-full bg-amber-400',
  messages: 'w-1.5 h-1.5 rounded-full bg-slate-400',
}

function ResultIcon({ type }: { type: string }) {
  if (type === 'law') return <Scale size={16} className="text-blue-500" />
  if (type === 'judge') return <Gavel size={16} className="text-emerald-500" />
  if (type === 'memory') return <Brain size={16} className="text-amber-500" />
  return <MessagesSquare size={16} className="text-slate-500" />
}

export default function SearchResults({ onForward, onQuote, onOpenMessage }: SearchResultsProps) {
  const data = useSearchStore((s) => s.data)
  const tab = useSearchStore((s) => s.tab)
  const setTab = useSearchStore((s) => s.setTab)
  const loading = useSearchStore((s) => s.loading)
  const error = useSearchStore((s) => s.error)
  const hasSearched = useSearchStore((s) => s.hasSearched)

  const visible = useMemo<SearchResult[]>(() => {
    if (!data) return []
    if (tab === 'all') {
      return [
        ...(data.results.law || []),
        ...(data.results.judge || []),
        ...(data.results.memory || []),
        ...(data.results.messages || []),
      ]
    }
    return (data.results[tab] || []) as SearchResult[]
  }, [data, tab])

  const failedSources = data ? Object.entries(data.errors || {}) : []

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Tab */}
      <div className="px-6 pt-4 pb-2 border-b border-slate-100">
        <div className="flex gap-1.5 flex-wrap">
          {SEARCH_TABS.map((t) => {
            const count = data
              ? t.key === 'all'
                ? data.counts.total
                : data.counts[t.key]
              : 0
            const active = tab === t.key
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key as SearchTab)}
                disabled={!data}
                className={`px-3 py-1.5 rounded-full text-xs transition-colors disabled:opacity-40 ${
                  active ? 'bg-blue-100 text-blue-700 font-medium' : 'text-slate-500 hover:bg-slate-100'
                }`}
              >
                {t.label}
                {data && <span className="ml-1 text-[10px] text-slate-400">{count}</span>}
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading && (
          <div className="flex items-center justify-center py-20 text-slate-400">
            <Loader2 size={20} className="animate-spin mr-2" />
            <span className="text-xs">检索中…</span>
          </div>
        )}

        {!loading && error && (
          <div className="max-w-3xl mx-auto p-3 rounded-lg bg-red-50 border border-red-200 text-xs text-red-600">
            {error}
          </div>
        )}

        {!loading && !error && failedSources.length > 0 && (
          <div className="max-w-3xl mx-auto mb-3 text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            部分来源暂不可用（已隔离）：
            {failedSources.map(([k]) => SEARCH_TABS.find((t) => t.key === k)?.label || k).join('、')}
          </div>
        )}

        {!loading && !hasSearched && (
          <div className="flex flex-col items-center justify-center py-24 text-slate-400">
            <Sparkles size={36} className="text-slate-200 mb-3" />
            <p className="text-sm">输入关键词，统一检索法规、类案、记忆与历史会话</p>
          </div>
        )}

        {!loading && hasSearched && visible.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center py-24 text-slate-400">
            <Search size={36} className="text-slate-200 mb-3" />
            <p className="text-sm">未找到匹配结果</p>
          </div>
        )}

        <div className="max-w-3xl mx-auto space-y-2.5">
          {!loading &&
            visible.map((r) => (
              <div
                key={`${r.type}-${'id' in r ? r.id : r.content}`}
                className="group bg-white border border-slate-200 rounded-xl p-4 hover:border-blue-300 transition-colors"
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-lg bg-slate-50 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <ResultIcon type={r.type} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className={DOT[r.type]} />
                      <span className="text-xs font-semibold text-slate-800 truncate">
                        {resultTitle(r)}
                      </span>
                      {r.type === 'messages' && (
                        <span className="text-[10px] text-slate-400">
                          {(r as MessageResult).sender_name || '用户'} · 第 {(r as MessageResult).round} 轮
                        </span>
                      )}
                      {(r.type === 'memory') && (
                        <span className="text-[10px] text-slate-400">
                          {relativeTime((r as MemoryResult).created_at)}
                        </span>
                      )}
                      {'score' in r && typeof r.score === 'number' && r.score > 0 && (
                        <span className="text-[10px] text-emerald-500">
                          {(r.score * 100).toFixed(0)}%匹配
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed line-clamp-3 whitespace-pre-wrap">
                      {resultBody(r)}
                    </p>

                    <div className="flex items-center gap-3 mt-2.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => onForward(r)}
                        className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-blue-600 transition-colors"
                      >
                        <Share2 size={12} />
                        转发到…
                      </button>
                      <button
                        onClick={() => onQuote(r)}
                        className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-blue-600 transition-colors"
                      >
                        <MessagesSquare size={12} />
                        引用并新建协同群
                      </button>
                      {r.type === 'messages' && (
                        <button
                          onClick={() => onOpenMessage(r as MessageResult)}
                          className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-blue-600 transition-colors"
                        >
                          <ExternalLink size={12} />
                          打开会话
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
        </div>
      </div>
    </div>
  )
}
