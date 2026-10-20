'use client'

/**
 * 知识库浏览（T3.2 次级入口）
 * 法条/类案/策略的分类树浏览 + 单域语义检索，替代旧 /knowledge 页面。
 * 只读浏览，转发/引用请回到统一搜索结果。
 */
import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, BookOpen, FileText, Loader2, RefreshCw, Scale, Search } from 'lucide-react'
import { listKnowledge, searchKnowledge } from '@/app/lib/api'

const DOMAIN_TABS = [
  { key: 'law', label: '法条库', icon: Scale },
  { key: 'judge', label: '法官库', icon: BookOpen },
  { key: 'lawyer', label: '律师库', icon: FileText },
]

const CATEGORIES: Record<string, { key: string; label: string }[]> = {
  law: [
    { key: '', label: '全部法条' },
    { key: '民事', label: '民事法律' },
    { key: '合同', label: '合同纠纷' },
    { key: '劳动', label: '劳动权益' },
    { key: '侵权', label: '侵权责任' },
    { key: '刑事', label: '刑事规范' },
  ],
  judge: [
    { key: '', label: '全部案例' },
    { key: '民事', label: '民事案件' },
    { key: '刑事', label: '刑事案件' },
    { key: '行政', label: '行政案件' },
  ],
  lawyer: [
    { key: '', label: '全部策略' },
    { key: '民事', label: '民事辩护' },
    { key: '刑事', label: '刑事辩护' },
  ],
}

/** 知识库条目字段随域而异（law_name / case_name / strategy_name…），按松散记录处理 */
type BrowseItem = { _id: string } & Record<string, unknown>

function toBrowseItem(raw: unknown, id: string): BrowseItem {
  return { ...(raw as Record<string, unknown>), _id: id }
}

function itemTitle(item: BrowseItem, domain: string): string {
  if (domain === 'law') return String(item.law_name ?? '未知法规')
  if (domain === 'judge') return String(item.case_name ?? '未知案例')
  if (domain === 'lawyer') return String(item.strategy_name ?? '未知策略')
  return String(item.source ?? '检索结果')
}

function itemBody(item: BrowseItem, domain: string): string {
  if (domain === 'judge') return String(item.judgment_result ?? item.content ?? '')
  if (domain === 'lawyer') return String(item.argument_template ?? item.content ?? '')
  return String(item.content ?? '')
}

interface KnowledgeBrowsePanelProps {
  onClose: () => void
}

export default function KnowledgeBrowsePanel({ onClose }: KnowledgeBrowsePanelProps) {
  const [domain, setDomain] = useState('law')
  const [category, setCategory] = useState('')
  const [keyword, setKeyword] = useState('')
  const [items, setItems] = useState<BrowseItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const pageSize = 20

  const fetchList = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listKnowledge(domain, category, '', page, pageSize)
      setItems((res.items || []).map((it, idx) => toBrowseItem(it, String((page - 1) * pageSize + idx))))
      setTotal(res.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : '获取数据失败')
    } finally {
      setLoading(false)
    }
  }, [domain, category, page])

  useEffect(() => {
    void fetchList()
  }, [fetchList])

  const doSearch = async () => {
    const q = keyword.trim()
    if (!q) return
    setLoading(true)
    setError(null)
    try {
      const res = await searchKnowledge(q, domain, 20)
      setItems((res.results || []).map((it, idx) => toBrowseItem(it, `s${idx}`)))
      setTotal(res.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : '搜索失败')
    } finally {
      setLoading(false)
    }
  }

  const changeDomain = (d: string) => {
    setDomain(d)
    setCategory('')
    setPage(1)
    setKeyword('')
    setExpanded(null)
  }

  const categories = CATEGORIES[domain] || []
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <header className="h-12 px-4 flex items-center justify-between border-b border-slate-100 flex-shrink-0">
        <div className="flex items-center gap-2">
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 transition-colors"
            title="返回搜索"
          >
            <ArrowLeft size={17} />
          </button>
          <BookOpen size={17} className="text-blue-500" />
          <span className="text-sm font-semibold text-slate-800">知识库浏览</span>
          <span className="text-[11px] text-slate-400">{total} 条</span>
        </div>
        <button
          onClick={() => void fetchList()}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 text-xs hover:bg-slate-50 transition-colors"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </header>

      <div className="flex-1 flex min-h-0">
        {/* 左侧：域 + 分类 */}
        <aside className="w-44 border-r border-slate-100 flex-shrink-0 overflow-y-auto bg-slate-50/60 py-3 px-2 space-y-4">
          <div>
            <p className="text-[11px] font-semibold text-slate-500 px-2 mb-2">知识领域</p>
            <div className="space-y-0.5">
              {DOMAIN_TABS.map(({ key, label, icon: Icon }) => {
                const active = domain === key
                return (
                  <button
                    key={key}
                    onClick={() => changeDomain(key)}
                    className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
                      active ? 'bg-blue-50 text-blue-600 font-medium' : 'text-slate-500 hover:bg-slate-100'
                    }`}
                  >
                    <Icon size={13} />
                    {label}
                  </button>
                )
              })}
            </div>
          </div>
          <div className="pt-2 border-t border-slate-100">
            <p className="text-[11px] font-semibold text-slate-500 px-2 mb-2">分类筛选</p>
            <div className="space-y-0.5">
              {categories.map((c) => {
                const active = category === c.key
                return (
                  <button
                    key={c.key}
                    onClick={() => {
                      setCategory(c.key)
                      setPage(1)
                      setKeyword('')
                    }}
                    className={`w-full text-left px-2.5 py-1.5 rounded-lg text-[11px] transition-colors ${
                      active ? 'bg-blue-50 text-blue-600 font-medium' : 'text-slate-500 hover:bg-slate-100'
                    }`}
                  >
                    {c.label}
                  </button>
                )
              })}
            </div>
          </div>
        </aside>

        {/* 右侧：搜索 + 列表 */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="p-4 pb-2 flex-shrink-0">
            <div className="relative max-w-2xl">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void doSearch()
                }}
                placeholder={`在${DOMAIN_TABS.find((t) => t.key === domain)?.label}中语义检索…`}
                className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-9 pr-20 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
              />
              <button
                onClick={() => void doSearch()}
                disabled={!keyword.trim() || loading}
                className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 rounded-md bg-blue-600 text-white text-xs hover:bg-blue-700 disabled:opacity-40 transition-colors"
              >
                检索
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-4 pb-4">
            {error && (
              <div className="max-w-2xl mb-3 p-3 rounded-lg bg-red-50 border border-red-200 text-xs text-red-600">
                {error}
              </div>
            )}
            {loading && items.length === 0 && (
              <div className="flex items-center justify-center py-20 text-slate-400">
                <Loader2 size={20} className="animate-spin mr-2" />
                <span className="text-xs">加载中…</span>
              </div>
            )}
            {!loading && items.length === 0 && !error && (
              <div className="flex flex-col items-center justify-center py-20 text-slate-400">
                <BookOpen size={32} className="text-slate-200 mb-3" />
                <p className="text-xs">暂无数据</p>
              </div>
            )}

            <div className="max-w-2xl space-y-2.5">
              {items.map((it) => {
                const isOpen = expanded === it._id
                return (
                  <div
                    key={it._id}
                    className="bg-white border border-slate-200 rounded-xl p-4 cursor-pointer hover:border-blue-300 transition-colors"
                    onClick={() => setExpanded(isOpen ? null : it._id)}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <h3 className="text-xs font-semibold text-slate-800 truncate">
                        {itemTitle(it, domain)}
                      </h3>
                      {'score' in it && Number(it.score) > 0 && (
                        <span className="text-[10px] text-emerald-500 flex-shrink-0">
                          {(Number(it.score) * 100).toFixed(0)}%匹配
                        </span>
                      )}
                    </div>
                    <p
                      className={`text-xs text-slate-600 leading-relaxed whitespace-pre-wrap ${
                        isOpen ? '' : 'line-clamp-2'
                      }`}
                    >
                      {itemBody(it, domain)}
                    </p>
                  </div>
                )
              })}
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-3 pt-4">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="text-xs px-3 py-1 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-30 transition-colors"
                >
                  上一页
                </button>
                <span className="text-xs text-slate-400 tabular-nums">
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="text-xs px-3 py-1 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-30 transition-colors"
                >
                  下一页
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
