'use client'

import { useState, useEffect, useCallback } from 'react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'
import {
  Search, BookOpen, Scale, FileText, ChevronRight, ExternalLink,
  Loader2, RefreshCw, Filter, Database, Hash, Calendar,
  CheckCircle2, TrendingUp, Star, Zap, Layers
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  searchKnowledge, listKnowledge,
  type KnowledgeSearchResult, type KnowledgeListItem
} from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

const DOMAIN_TABS = [
  { key: 'law', label: '法条库', icon: Scale, color: 'text-blue-400', bg: 'bg-blue-500/10' },
  { key: 'judge', label: '法官库', icon: BookOpen, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  { key: 'lawyer', label: '律师库', icon: FileText, color: 'text-orange-400', bg: 'bg-orange-500/10' },
]

const LAW_CATEGORIES = [
  { key: '', label: '全部法条', count: 0 },
  { key: '民事', label: '民事法律', icon: '⚖️' },
  { key: '合同', label: '合同纠纷', icon: '📝' },
  { key: '劳动', label: '劳动权益', icon: '👷' },
  { key: '物权', label: '物权保护', icon: '🏠' },
  { key: '婚姻家庭', label: '婚姻家庭', icon: '💑' },
  { key: '侵权', label: '侵权责任', icon: '🛡️' },
  { key: '刑事', label: '刑事规范', icon: '⚡' },
  { key: '行政', label: '行政诉讼', icon: '📋' },
]

const HOT_SEARCHES = ['民法典第七百零三条', '劳动合同解除赔偿', '租房押金退还条件', '诉讼时效三年规定']

type SearchResultItem = KnowledgeSearchResult & { id: string }
type ListItemWithId = KnowledgeListItem & { id: string }

export default function KnowledgePage() {
  const { authed } = useChatStore()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeDomain, setActiveDomain] = useState('law')
  const [activeCategory, setActiveCategory] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResultItem[]>([])
  const [listResults, setListResults] = useState<ListItemWithId[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(15)
  const [loading, setLoading] = useState(false)
  const [searchMode, setSearchMode] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchList = useCallback(async () => {
    if (!authed) return
    setLoading(true); setError(null)
    try {
      const res = await listKnowledge(activeDomain, activeCategory, '', page, pageSize)
      setListResults((res.items || []).map((it, idx) => ({ ...it, id: String((page - 1) * pageSize + idx) })))
      setTotal(res.total)
    } catch (e) { setError((e as Error).message || '获取数据失败') }
    finally { setLoading(false) }
  }, [authed, activeDomain, activeCategory, page, pageSize])

  useEffect(() => { if (!searchMode) fetchList() }, [searchMode, fetchList])

  const handleSearch = async (overrideQuery?: string) => {
    const q = overrideQuery || searchQuery
    if (!q.trim() || !authed) return
    setLoading(true); setError(null); setSearchMode(true)
    try {
      const res = await searchKnowledge(q, activeDomain, 20)
      setSearchResults((res.results || []).map((it, idx) => ({ ...it, id: String(idx) })))
      setTotal(res.total)
    } catch (e) { setError((e as Error).message || '搜索失败') }
    finally { setLoading(false) }
  }

  const handleClearSearch = () => { setSearchQuery(''); setSearchMode(false); setSearchResults([]); setPage(1) }

  const handleDomainChange = (domain: string) => {
    setActiveDomain(domain); setActiveCategory(''); setPage(1)
    if (searchMode) { setSearchMode(false); setSearchQuery(''); setSearchResults([]) }
  }

  const displayItems = searchMode ? searchResults : listResults
  const totalPages = Math.ceil(total / pageSize)
  const currentTab = DOMAIN_TABS.find(t => t.key === activeDomain) || DOMAIN_TABS[0]
  const domainStats = { law: { total: total, updated: '2024-05-01' }, judge: { total: total, updated: '2024-04-15' }, lawyer: { total: total, updated: '2024-03-20' } }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex flex-col bg-[#0a1628] overflow-hidden">
        {/* 顶部标题栏 */}
        <header className="h-14 border-b border-white/5 flex items-center justify-between px-6 bg-[#0d1a2d]/80 backdrop-blur-sm flex-shrink-0 z-10">
          <div className="flex items-center gap-3">
            <Database size={20} className="text-blue-400" />
            <h1 className="text-base font-semibold text-gold-200">法律知识库</h1>
            <span className="text-[10px] text-gold-200/35">|</span>
            <span className="text-xs text-gold-200/50">检索法律法规 · 判例文书 · 辩护策略</span>
          </div>
          <div className="flex items-center gap-3">
            {!searchMode && (
              <button onClick={fetchList} disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 text-gold-200/60 text-xs hover:bg-white/5 transition-all">
                <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> 刷新数据
              </button>
            )}
          </div>
        </header>

        {/* 主内容区 */}
        <div className="flex-1 flex overflow-hidden">

          {/* 左侧分类面板 */}
          <aside className="w-52 border-r border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/40">
            <div className="p-4 space-y-4">
              {/* 域切换 */}
              <div>
                <h4 className="text-[11px] font-semibold text-gold-200/60 mb-2.5">知识领域</h4>
                <div className="space-y-1">
                  {DOMAIN_TABS.map(tab => {
                    const IconComp = tab.icon; const isActive = activeDomain === tab.key
                    return (
                      <button key={tab.key} onClick={() => handleDomainChange(tab.key)}
                        className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-all ${
                          isActive ? `${tab.bg} border ${tab.color.replace('text-', 'border-')} ${tab.color} font-medium` : 'hover:bg-white/[0.02] text-gold-200/55'
                        }`}>
                        <IconComp size={14} />
                        <span className="text-xs">{tab.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* 分类筛选 */}
              {activeDomain === 'law' && !searchMode && (
                <div className="pt-3 border-t border-white/5">
                  <h4 className="text-[11px] font-semibold text-gold-200/60 mb-2.5">法规分类</h4>
                  <div className="space-y-0.5">
                    {LAW_CATEGORIES.slice(0, 8).map(cat => {
                      const isActive = activeCategory === cat.key
                      return (
                        <button key={cat.key} onClick={() => { setActiveCategory(cat.key); setPage(1) }}
                          className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition-all ${
                            isActive ? 'bg-blue-500/10 text-blue-400 font-medium' : 'text-gold-200/45 hover:bg-white/[0.02]'
                          }`}>
                          {cat.icon && <span className="text-sm">{cat.icon}</span>}
                          <span className="text-[11px] flex-1 truncate">{cat.label}</span>
                          {isActive && <CheckCircle2 size={11} />}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* 统计信息 */}
              <div className="pt-3 border-t border-white/5 space-y-2">
                <h4 className="text-[11px] font-semibold text-gold-200/60">数据概览</h4>
                <div className="grid grid-cols-2 gap-1.5 text-center">
                  <div className="rounded-lg bg-blue-500/[0.04] p-2">
                    <div className="text-sm font-bold text-blue-400">{total}</div>
                    <div className="text-[9px] text-gold-200/30">总记录数</div>
                  </div>
                  <div className="rounded-lg bg-emerald-500/[0.04] p-2">
                    <div className="text-sm font-bold text-emerald-400">{LAW_CATEGORIES.length - 1}</div>
                    <div className="text-[9px] text-gold-200/30">分类数</div>
                  </div>
                </div>
              </div>
            </div>
          </aside>

          {/* 中间内容区 */}
          <section className="flex-1 flex flex-col min-w-0 overflow-hidden">
            {/* 搜索栏 */}
            <div className="p-4 pb-2 flex-shrink-0">
              <div className="relative max-w-2xl mx-auto">
                <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gold-200/25" />
                <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  placeholder={`智能检索${currentTab.label}...`}
                  disabled={!authed || loading}
                  className="w-full pl-10 pr-24 py-2.5 rounded-xl bg-white/5 border border-white/10
                           text-xs text-gold-200/85 placeholder:text-gold-200/25
                           focus:outline-none focus:border-blue-400/35 focus:ring-1 focus:ring-blue-400/10 transition-all
                           disabled:opacity-40" />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  {searchMode && (
                    <button onClick={handleClearSearch} className="px-2 py-1 text-[10px] text-gold-200/40 hover:text-red-400 transition-colors">清除</button>
                  )}
                  <button onClick={() => handleSearch()} disabled={!searchQuery.trim() || !authed || loading}
                    className="gold-btn-sm text-[10px] px-3 py-1 disabled:opacity-40">搜索</button>
                </div>
              </div>

              {/* 热门搜索 */}
              {!searchMode && (
                <div className="flex items-center gap-2 mt-2.5 max-w-2xl mx-auto">
                  <Zap size={11} className="text-amber-400" />
                  <span className="text-[10px] text-gold-200/30">热门：</span>
                  {HOT_SEARCHES.map((kw, i) => (
                    <button key={i} onClick={() => { setSearchQuery(kw); handleSearch(kw) }}
                      className="text-[10px] px-2 py-0.5 rounded-full border border-white/[0.06] text-gold-200/35 hover:text-blue-400 hover:border-blue-400/20 transition-all">
                      {kw}
                    </button>
                  ))}
                </div>
              )}

              {/* 结果计数 */}
              <div className="flex items-center justify-between mt-3 max-w-2xl mx-auto">
                <span className="text-[10px] text-gold-200/35">
                  {searchMode ? `搜索到 ${total} 条结果` : `共 ${total} 条记录`}
                </span>
                <div className="flex items-center gap-1 text-[10px] text-gold-200/30">
                  <Filter size={10} /> 筛选
                </div>
              </div>
            </div>

            {/* 结果列表 */}
            <div className="flex-1 overflow-y-auto px-4 pb-4">
              {error && (
                <div className="max-w-2xl mx-auto mb-3 p-3 rounded-lg bg-red-400/10 border border-red-400/20 text-red-400 text-[10px]">{error}</div>
              )}

              {loading && displayItems.length === 0 ? (
                <div className="flex items-center justify-center py-24"><Loader2 size={22} className="animate-spin text-blue-400" /><span className="text-xs text-gold-200/35 ml-3">加载中...</span></div>
              ) : (
                <AnimatePresence>
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="max-w-2xl mx-auto space-y-2.5">
                    {displayItems.map(data => (
                      <motion.div key={data.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                        className="glass-card-static p-4 group cursor-pointer hover:border-white/10 transition-all"
                        onClick={() => window.open('#', '_blank')}>
                        {renderItem(data, activeDomain)}
                      </motion.div>
                    ))}
                  </motion.div>
                </AnimatePresence>
              )}

              {!loading && displayItems.length === 0 && !error && (
                <div className="flex flex-col items-center justify-center py-24 max-w-2xl mx-auto">
                  <Database size={36} className="text-gold-200/15 mb-3" />
                  <p className="text-sm text-gold-200/35 font-medium">{searchMode ? '未找到匹配结果' : '暂无数据'}</p>
                  <p className="text-[10px] text-gold-200/20 mt-1">{searchMode ? '请尝试调整关键词或切换知识域' : '请确认数据库已初始化并连接后端服务'}</p>
                </div>
              )}

              {/* 分页 */}
              {!searchMode && totalPages > 1 && (
                <div className="flex items-center justify-center gap-3 pt-4 pb-2">
                  <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
                    className="text-[10px] px-3 py-1 rounded-lg border border-white/10 text-gold-200/45 hover:text-gold-200/70 hover:border-white/15 disabled:opacity-30 transition-all">
                    ← 上一页
                  </button>
                  <span className="text-[10px] text-gold-200/35 tabular-nums">{page} / {totalPages}</span>
                  <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                    className="text-[10px] px-3 py-1 rounded-lg border border-white/10 text-gold-200/45 hover:text-gold-200/70 hover:border-white/15 disabled:opacity-30 transition-all">
                    下一页 →
                  </button>
                </div>
              )}
            </div>
          </section>

          {/* 右侧详情面板 */}
          <aside className="w-64 border-l border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/40 hidden lg:block">
            <div className="p-4 space-y-4">
              {/* 当前域信息 */}
              <div className={`${currentTab.bg} rounded-xl p-3 border ${currentTab.color.replace('text-', 'border-')} border-opacity-20`}>
                <div className="flex items-center gap-2 mb-2">
                  {(() => { const Ic = currentTab.icon; return <Ic size={14} className={currentTab.color} /> })()}
                  <span className={`text-xs font-semibold ${currentTab.color}`}>{currentTab.label}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-center">
                  <div><div className="text-sm font-bold text-gold-200">{total}</div><div className="text-[9px] text-gold-200/30">条记录</div></div>
                  <div><div className="text-sm font-bold text-gold-200">{LAW_CATEGORIES.length - 1}</div><div className="text-[9px] text-gold-200/30">个分类</div></div>
                </div>
              </div>

              {/* 快捷入口 */}
              <div>
                <h4 className="text-[11px] font-semibold text-gold-200/60 mb-2.5 flex items-center gap-1.5">
                  <Star size={12} className="text-amber-400" /> 常用检索
                </h4>
                <div className="space-y-1.5">
                  {[
                    { title: '民法典总则编', desc: '民事主体与权利能力', tag: '高频' },
                    { title: '合同编通则', desc: '订立·履行·违约责任', tag: '常用' },
                    { title: '侵权责任编', desc: '归责原则与赔偿范围', tag: '重要' },
                    { title: '婚姻家庭编', desc: '结婚·离婚·财产分割', tag: '' },
                  ].map((item, i) => (
                    <button key={i} onClick={() => { setSearchQuery(item.title); handleSearch(item.title) }}
                      className="w-full flex items-start gap-2 p-2.5 rounded-lg hover:bg-white/[0.02] text-left group transition-all">
                      <Hash size={11} className="text-blue-400/50 mt-0.5 flex-shrink-0 group-hover:text-blue-400" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] text-gold-200/65 group-hover:text-gold-200 truncate">{item.title}</span>
                          {item.tag && <span className="text-[8px] px-1 py-px rounded bg-amber-400/10 text-amber-400 flex-shrink-0">{item.tag}</span>}
                        </div>
                        <span className="text-[9px] text-gold-200/25 line-clamp-1">{item.desc}</span>
                      </div>
                      <ChevronRight size={10} className="text-gold-200/15 mt-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </button>
                  ))}
                </div>
              </div>

              {/* 更新时间 */}
              <div className="pt-3 border-t border-white/5">
                <div className="flex items-center gap-2 text-[10px] text-gold-200/30">
                  <Calendar size={10} />
                  <span>最近更新：{domainStats[activeDomain as keyof typeof domainStats]?.updated || '--'}</span>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </main>
      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}

function renderItem(data: SearchResultItem | ListItemWithId, domain: string) {
  if ('score' in data) return renderSearchItem(data as SearchResultItem)
  const row = data as ListItemWithId
  if (domain === 'law') return renderLawItem(row)
  if (domain === 'judge') return renderJudgeItem(row)
  if (domain === 'lawyer') return renderLawyerItem(row)
  return null
}

function renderLawItem(row: ListItemWithId) {
  return (
    <>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Scale size={14} className="text-blue-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <h3 className="text-[11px] font-semibold text-gold-200 group-hover:text-blue-300 truncate">{row.law_name || '未知法规'}</h3>
            <span className="text-[9px] px-1.5 py-px rounded-full bg-blue-400/10 text-blue-400 flex-shrink-0">{row.law_type || '未分类'}</span>
            {row.article_number && <span className="text-[9px] px-1.5 py-px rounded-full bg-purple-400/10 text-purple-400 flex-shrink-0">第{row.article_number}条</span>}
          </div>
          {row.article_title && <p className="text-[10px] text-gold-200/50 mb-1 truncate">{row.article_title}</p>}
          <p className="text-[10px] text-gold-200/35 leading-relaxed line-clamp-2">{row.content || '暂无内容'}</p>
          <div className="flex items-center gap-3 mt-2 flex-wrap">
            {row.chapter && <span className="text-[9px] text-gold-200/25">📖 {row.chapter}</span>}
            {row.effective_date && <span className="text-[9px] text-gold-200/25">📅 {row.effective_date}</span>}
            {row.status && <span className="text-[9px] text-gold-200/25">{row.status}</span>}
          </div>
        </div>
        <ChevronRight size={13} className="text-gold-200/15 group-hover:text-gold-300 flex-shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-all" />
      </div>
    </>
  )
}

function renderJudgeItem(row: ListItemWithId) {
  return (
    <>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center flex-shrink-0 mt-0.5">
          <BookOpen size={14} className="text-emerald-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-[11px] font-semibold text-gold-200 group-hover:text-emerald-300 truncate">{row.case_name || '未知案例'}</h3>
            <span className="text-[9px] px-1.5 py-px rounded-full bg-emerald-400/10 text-emerald-400 flex-shrink-0">{row.case_type || '未分类'}</span>
          </div>
          {row.cause_of_action && <p className="text-[10px] text-gold-200/50 mb-1 truncate">案由：{row.cause_of_action}</p>}
          {row.judgment_result && <p className="text-[10px] text-gold-200/35 leading-relaxed line-clamp-2">{row.judgment_result}</p>}
          <div className="flex items-center gap-3 mt-2 flex-wrap">
            {row.case_number && <span className="text-[9px] text-gold-200/25">🔢 {row.case_number}</span>}
            {row.court_name && <span className="text-[9px] text-gold-200/25">⚖️ {row.court_name}</span>}
            {row.judgment_date && <span className="text-[9px] text-gold-200/25">📅 {row.judgment_date}</span>}
          </div>
        </div>
        <ChevronRight size={13} className="text-gold-200/15 group-hover:text-gold-300 flex-shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-all" />
      </div>
    </>
  )
}

function renderLawyerItem(row: ListItemWithId) {
  return (
    <>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-orange-500/10 flex items-center justify-center flex-shrink-0 mt-0.5">
          <FileText size={14} className="text-orange-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-[11px] font-semibold text-gold-200 group-hover:text-orange-300 truncate">{row.strategy_name || '未知策略'}</h3>
            <span className="text-[9px] px-1.5 py-px rounded-full bg-orange-400/10 text-orange-400 flex-shrink-0">{row.case_type || '未分类'}</span>
            {row.success_rate != null && row.success_rate !== undefined &&
              <span className="text-[9px] px-1.5 py-px rounded-full bg-green-400/10 text-green-400 flex-shrink-0">成功率{row.success_rate}%</span>}
          </div>
          {row.applicable_scenario && <p className="text-[10px] text-gold-200/50 mb-1 truncate">适用场景：{row.applicable_scenario}</p>}
          {row.argument_template && <p className="text-[10px] text-gold-200/35 leading-relaxed line-clamp-2">{row.argument_template}</p>}
        </div>
        <ChevronRight size={13} className="text-gold-200/15 group-hover:text-gold-300 flex-shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-all" />
      </div>
    </>
  )
}

function renderSearchItem(result: SearchResultItem) {
  return (
    <>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-gold-400/10 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Search size={14} className="text-gold-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-[11px] font-semibold text-gold-200 group-hover:text-gold-300 truncate">{result.source || '检索结果'}</h3>
            <span className="text-[9px] px-1.5 py-px rounded-full bg-gold-400/10 text-gold-400 flex-shrink-0">{result.doc_type || result.domain || '法律'}</span>
            {result.score > 0 && <span className="text-[9px] px-1.5 py-px rounded-full bg-green-400/10 text-green-400 flex-shrink-0">{(result.score * 100).toFixed(0)}%匹配</span>}
          </div>
          <p className="text-[10px] text-gold-200/35 leading-relaxed line-clamp-3">{result.content || '暂无内容'}</p>
        </div>
        <ChevronRight size={13} className="text-gold-200/15 group-hover:text-gold-300 flex-shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-all" />
      </div>
    </>
  )
}
