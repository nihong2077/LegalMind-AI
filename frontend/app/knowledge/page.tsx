'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'
import {
  Search, BookOpen, Scale, FileText, ChevronRight,
  Loader2, RefreshCw, Filter, Database, Hash, Calendar,
  CheckCircle2, Zap, X, Copy, Check,
  Gavel, Shield
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  searchKnowledge, listKnowledge,
  type KnowledgeSearchResult, type KnowledgeListItem
} from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

/* ========== 常量配置 ========== */

const DOMAIN_TABS = [
  { key: 'law', label: '法条库', icon: Scale, color: 'text-blue-400', bg: 'bg-blue-50', border: 'border-blue-200' },
  { key: 'judge', label: '法官库', icon: BookOpen, color: 'text-emerald-400', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  { key: 'lawyer', label: '律师库', icon: FileText, color: 'text-orange-400', bg: 'bg-orange-50', border: 'border-orange-200' },
]

const LAW_CATEGORIES = [
  { key: '', label: '全部法条' },
  { key: '民事', label: '民事法律' },
  { key: '合同', label: '合同纠纷' },
  { key: '劳动', label: '劳动权益' },
  { key: '物权', label: '物权保护' },
  { key: '婚姻家庭', label: '婚姻家庭' },
  { key: '侵权', label: '侵权责任' },
  { key: '刑事', label: '刑事规范' },
  { key: '行政', label: '行政诉讼' },
]

const JUDGE_CATEGORIES = [
  { key: '', label: '全部案例' },
  { key: '民事', label: '民事案件' },
  { key: '刑事', label: '刑事案件' },
  { key: '行政', label: '行政案件' },
]

const LAWYER_CATEGORIES = [
  { key: '', label: '全部策略' },
  { key: '民事', label: '民事辩护' },
  { key: '刑事', label: '刑事辩护' },
]

const HOT_SEARCHES = ['借款合同纠纷', '故意伤害罪量刑', '劳动合同解除赔偿', '无罪辩护']

type SearchResultItem = KnowledgeSearchResult & { id: string }
type ListItemWithId = KnowledgeListItem & { id: string }

/* ========== 详情模态框 ========== */

function DetailModal({
  item,
  domain,
  onClose,
}: {
  item: SearchResultItem | ListItemWithId | null
  domain: string
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)

  if (!item) return null

  const handleCopy = () => {
    const text = getItemFullText(item, domain)
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // 根据域提取详情字段
  const fields = getDetailFields(item, domain)

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          transition={{ duration: 0.2 }}
          className="w-full max-w-2xl max-h-[85vh] mx-4 rounded-2xl overflow-hidden"
          style={{ background: 'rgba(255, 255, 255, 0.98)', border: '1px solid #e2e8f0' }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* 模态框头部 */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
            <div className="flex items-center gap-3 min-w-0">
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                domain === 'law' ? 'bg-blue-50' : domain === 'judge' ? 'bg-emerald-50' : 'bg-orange-50'
              }`}>
                {domain === 'law' ? <Scale size={15} className="text-blue-400" /> :
                 domain === 'judge' ? <Gavel size={15} className="text-emerald-400" /> :
                 <Shield size={15} className="text-orange-400" />}
              </div>
              <h2 className="text-sm font-semibold text-slate-800 truncate">
                {fields.title || '详情'}
              </h2>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button onClick={handleCopy}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-gray-200 text-slate-400 text-[10px] hover:bg-slate-50 transition-all">
                {copied ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                {copied ? '已复制' : '复制'}
              </button>
              <button onClick={onClose}
                className="p-1.5 rounded-lg border border-gray-200 text-slate-400 hover:bg-slate-50 transition-all">
                <X size={13} />
              </button>
            </div>
          </div>

          {/* 模态框内容 */}
          <div className="overflow-y-auto p-5 space-y-4" style={{ maxHeight: 'calc(85vh - 60px)' }}>
            {/* 标签区 */}
            <div className="flex flex-wrap gap-2">
              {fields.tags.map((tag, i) => (
                <span key={i} className={`text-[10px] px-2 py-0.5 rounded-full ${
                  tag.type === 'primary' ? 'bg-blue-400/10 text-blue-400' :
                  tag.type === 'success' ? 'bg-green-400/10 text-green-400' :
                  tag.type === 'warning' ? 'bg-amber-400/10 text-amber-400' :
                  'bg-slate-50 text-slate-500'
                }`}>{tag.label}</span>
              ))}
            </div>

            {/* 元数据区 */}
            {fields.meta.length > 0 && (
              <div className="grid grid-cols-2 gap-3">
                {fields.meta.map((m, i) => (
                  <div key={i} className="rounded-lg bg-slate-50 p-2.5">
                    <div className="text-[9px] text-slate-400 mb-0.5">{m.label}</div>
                    <div className="text-[11px] text-slate-600 truncate">{m.value || '--'}</div>
                  </div>
                ))}
              </div>
            )}

            {/* 正文内容 */}
            {fields.content && (
              <div>
                <h4 className="text-[10px] font-semibold text-slate-500 mb-2 uppercase tracking-wider">
                  {domain === 'law' ? '法条内容' : domain === 'judge' ? '裁判详情' : '策略内容'}
                </h4>
                <div className="rounded-xl bg-slate-50 border border-gray-200 p-4">
                  <p className="text-[11px] text-slate-600 leading-[1.8] whitespace-pre-wrap">{fields.content}</p>
                </div>
              </div>
            )}

            {/* 匹配分数（搜索结果） */}
            {'score' in item && (item as SearchResultItem).score > 0 && (
              <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
                <span className="text-[10px] text-slate-400">语义匹配度</span>
                <div className="flex-1 h-1.5 rounded-full bg-slate-50 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-400"
                    style={{ width: `${Math.min(100, (item as SearchResultItem).score * 100)}%` }}
                  />
                </div>
                <span className="text-[10px] text-emerald-400 font-medium">
                  {((item as SearchResultItem).score * 100).toFixed(1)}%
                </span>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

/* ========== 辅助函数 ========== */

function getCategoriesForDomain(domain: string) {
  if (domain === 'judge') return JUDGE_CATEGORIES
  if (domain === 'lawyer') return LAWYER_CATEGORIES
  return LAW_CATEGORIES
}

function getItemFullText(item: SearchResultItem | ListItemWithId, domain: string): string {
  const row = item as ListItemWithId
  if (domain === 'law') {
    return `${row.law_name || ''}\n${row.article_title ? row.article_title + '\n' : ''}${row.content || ''}`
  }
  if (domain === 'judge') {
    return `${row.case_name || ''}\n案号: ${row.case_number || ''}\n法院: ${row.court_name || ''}\n案由: ${row.cause_of_action || ''}\n裁判结果: ${row.judgment_result || ''}`
  }
  return `${row.strategy_name || ''}\n适用场景: ${row.applicable_scenario || ''}\n${row.argument_template || ''}`
}

interface DetailTag { label: string; type: 'primary' | 'success' | 'warning' | 'default' }
interface DetailMeta { label: string; value: string }

function getDetailFields(item: SearchResultItem | ListItemWithId, domain: string) {
  const row = item as ListItemWithId
  const tags: DetailTag[] = []
  const meta: DetailMeta[] = []
  let title = ''
  let content = ''

  if ('score' in item) {
    // 搜索结果
    const sr = item as SearchResultItem
    title = sr.source || '检索结果'
    content = sr.content || ''
    if (sr.doc_type) tags.push({ label: sr.doc_type, type: 'primary' })
    if (sr.domain) tags.push({ label: sr.domain === 'law' ? '法条' : sr.domain === 'judge' ? '裁判' : '律师', type: 'warning' })
    if (sr.score > 0) tags.push({ label: `${(sr.score * 100).toFixed(0)}%匹配`, type: 'success' })
    return { title, content, tags, meta }
  }

  if (domain === 'law') {
    title = String(row.law_name || '未知法规')
    content = String(row.content || '')
    if (row.law_type) tags.push({ label: String(row.law_type), type: 'primary' })
    if (row.article_number) tags.push({ label: `第${row.article_number}条`, type: 'warning' })
    if (row.chapter) meta.push({ label: '章节', value: String(row.chapter) })
    if (row.section) meta.push({ label: '节', value: String(row.section) })
    if (row.article_title) meta.push({ label: '条目标题', value: String(row.article_title) })
    if (row.effective_date) meta.push({ label: '生效日期', value: String(row.effective_date) })
    if (row.status) meta.push({ label: '效力状态', value: String(row.status) })
  } else if (domain === 'judge') {
    title = String(row.case_name || '未知案例')
    content = String(row.judgment_result || '')
    if (row.case_type) tags.push({ label: String(row.case_type), type: 'primary' })
    if (row.case_number) meta.push({ label: '案号', value: String(row.case_number) })
    if (row.court_name) meta.push({ label: '审理法院', value: String(row.court_name) })
    if (row.cause_of_action) meta.push({ label: '案由', value: String(row.cause_of_action) })
    if (row.judgment_date) meta.push({ label: '裁判日期', value: String(row.judgment_date) })
  } else {
    title = String(row.strategy_name || '未知策略')
    content = String(row.argument_template || '')
    if (row.case_type) tags.push({ label: String(row.case_type), type: 'primary' })
    if (row.success_rate != null) tags.push({ label: `成功率${row.success_rate}%`, type: 'success' })
    if (row.applicable_scenario) meta.push({ label: '适用场景', value: String(row.applicable_scenario) })
  }

  return { title, content, tags, meta }
}

/* ========== 主页面 ========== */

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
  const [selectedItem, setSelectedItem] = useState<SearchResultItem | ListItemWithId | null>(null)
  const [showFilter, setShowFilter] = useState(false)
  const searchInputRef = useRef<HTMLInputElement>(null)

  const categories = getCategoriesForDomain(activeDomain)

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

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex flex-col bg-white overflow-hidden">
        {/* 顶部标题栏 */}
        <header className="h-14 border-b border-gray-200 flex items-center justify-between px-6 bg-white backdrop-blur-sm flex-shrink-0 z-10">
          <div className="flex items-center gap-3">
            <Database size={20} className="text-blue-400" />
            <h1 className="text-base font-semibold text-slate-800">法律知识库</h1>
            <span className="text-[10px] text-slate-400">|</span>
            <span className="text-xs text-slate-400">检索法律法规 · 判例文书 · 辩护策略</span>
          </div>
          <div className="flex items-center gap-3">
            {!searchMode && (
              <button onClick={fetchList} disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 text-slate-600 text-xs hover:bg-slate-50 transition-all">
                <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> 刷新
              </button>
            )}
          </div>
        </header>

        {/* 主内容区 */}
        <div className="flex-1 flex overflow-hidden">

          {/* 左侧分类面板 */}
          <aside className="w-52 border-r border-gray-200 flex-shrink-0 overflow-y-auto bg-slate-50">
            <div className="p-4 space-y-4">
              {/* 域切换 */}
              <div>
                <h4 className="text-[11px] font-semibold text-slate-600 mb-2.5">知识领域</h4>
                <div className="space-y-1">
                  {DOMAIN_TABS.map(tab => {
                    const IconComp = tab.icon; const isActive = activeDomain === tab.key
                    return (
                      <button key={tab.key} onClick={() => handleDomainChange(tab.key)}
                        className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-all ${
                          isActive ? `${tab.bg} border ${tab.border} ${tab.color} font-medium` : 'hover:bg-slate-50 text-slate-500'
                        }`}>
                        <IconComp size={14} />
                        <span className="text-xs">{tab.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* 分类筛选 */}
              {!searchMode && (
                <div className="pt-3 border-t border-gray-200">
                  <h4 className="text-[11px] font-semibold text-slate-600 mb-2.5">分类筛选</h4>
                  <div className="space-y-0.5">
                    {categories.map(cat => {
                      const isActive = activeCategory === cat.key
                      return (
                        <button key={cat.key} onClick={() => { setActiveCategory(cat.key); setPage(1) }}
                          className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition-all ${
                            isActive ? 'bg-blue-50 text-blue-400 font-medium' : 'text-slate-500 hover:bg-slate-50'
                          }`}>
                          <span className="text-[11px] flex-1 truncate">{cat.label}</span>
                          {isActive && <CheckCircle2 size={11} />}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* 统计信息 */}
              <div className="pt-3 border-t border-gray-200 space-y-2">
                <h4 className="text-[11px] font-semibold text-slate-600">数据概览</h4>
                <div className="grid grid-cols-2 gap-1.5 text-center">
                  <div className="rounded-lg bg-blue-50 p-2">
                    <div className="text-sm font-bold text-blue-400">{total.toLocaleString()}</div>
                    <div className="text-[9px] text-slate-400">总记录数</div>
                  </div>
                  <div className="rounded-lg bg-emerald-50 p-2">
                    <div className="text-sm font-bold text-emerald-400">{categories.length - 1}</div>
                    <div className="text-[9px] text-slate-400">分类数</div>
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
                <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-300" />
                <input ref={searchInputRef} value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  placeholder={`智能检索${currentTab.label}...`}
                  disabled={!authed || loading}
                  className="w-full pl-10 pr-24 py-2.5 rounded-xl bg-slate-50 border border-gray-200
                           text-xs text-slate-700 placeholder:text-slate-400
                           focus:outline-none focus:border-blue-400/35 focus:ring-1 focus:ring-blue-400/10 transition-all
                           disabled:opacity-40" />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  {searchMode && (
                    <button onClick={handleClearSearch} className="px-2 py-1 text-[10px] text-slate-500 hover:text-red-400 transition-colors">清除</button>
                  )}
                  <button onClick={() => handleSearch()} disabled={!searchQuery.trim() || !authed || loading}
                    className="gold-btn-sm text-[10px] px-3 py-1 disabled:opacity-40">搜索</button>
                </div>
              </div>

              {/* 热门搜索 */}
              {!searchMode && (
                <div className="flex items-center gap-2 mt-2.5 max-w-2xl mx-auto flex-wrap">
                  <Zap size={11} className="text-amber-400 flex-shrink-0" />
                  <span className="text-[10px] text-slate-400 flex-shrink-0">热门：</span>
                  {HOT_SEARCHES.map((kw, i) => (
                    <button key={i} onClick={() => { setSearchQuery(kw); handleSearch(kw) }}
                      className="text-[10px] px-2 py-0.5 rounded-full border border-gray-200 text-slate-400 hover:text-blue-400 hover:border-blue-200 transition-all">
                      {kw}
                    </button>
                  ))}
                </div>
              )}

              {/* 结果计数 + 筛选切换 */}
              <div className="flex items-center justify-between mt-3 max-w-2xl mx-auto">
                <span className="text-[10px] text-slate-400">
                  {searchMode ? `语义搜索到 ${total} 条结果` : `共 ${total.toLocaleString()} 条记录`}
                </span>
                <button onClick={() => setShowFilter(!showFilter)}
                  className={`flex items-center gap-1 text-[10px] transition-all ${showFilter ? 'text-blue-400' : 'text-slate-400 hover:text-slate-400'}`}>
                  <Filter size={10} /> 筛选
                </button>
              </div>

              {/* 展开筛选条 */}
              <AnimatePresence>
                {showFilter && !searchMode && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }} className="overflow-hidden max-w-2xl mx-auto">
                    <div className="flex flex-wrap gap-1.5 pt-2 pb-1">
                      {categories.map(cat => (
                        <button key={cat.key} onClick={() => { setActiveCategory(cat.key); setPage(1) }}
                          className={`text-[10px] px-2.5 py-1 rounded-full border transition-all ${
                            activeCategory === cat.key
                              ? 'border-blue-400/30 bg-blue-400/10 text-blue-400'
                              : 'border-gray-200 text-slate-400 hover:border-gray-200'
                          }`}>
                          {cat.label}
                        </button>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* 结果列表 */}
            <div className="flex-1 overflow-y-auto px-4 pb-4">
              {error && (
                <div className="max-w-2xl mx-auto mb-3 p-3 rounded-lg bg-red-400/10 border border-red-400/20 text-red-400 text-[10px]">{error}</div>
              )}

              {loading && displayItems.length === 0 ? (
                <div className="flex items-center justify-center py-24">
                  <Loader2 size={22} className="animate-spin text-blue-400" />
                  <span className="text-xs text-slate-400 ml-3">加载中...</span>
                </div>
              ) : (
                <AnimatePresence>
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="max-w-2xl mx-auto space-y-2.5">
                    {displayItems.map(data => (
                      <motion.div key={data.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                        className="glass-card-static p-4 group cursor-pointer hover:border-gray-200 transition-all"
                        onClick={() => setSelectedItem(data)}>
                        {renderItem(data, activeDomain)}
                      </motion.div>
                    ))}
                  </motion.div>
                </AnimatePresence>
              )}

              {!loading && displayItems.length === 0 && !error && (
                <div className="flex flex-col items-center justify-center py-24 max-w-2xl mx-auto">
                  <Database size={36} className="text-slate-200 mb-3" />
                  <p className="text-sm text-slate-400 font-medium">{searchMode ? '未找到匹配结果' : '暂无数据'}</p>
                  <p className="text-[10px] text-slate-300 mt-1">{searchMode ? '请尝试调整关键词或切换知识域' : '请确认数据库已初始化并连接后端服务'}</p>
                </div>
              )}

              {/* 分页 */}
              {!searchMode && totalPages > 1 && (
                <div className="flex items-center justify-center gap-3 pt-4 pb-2">
                  <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
                    className="text-[10px] px-3 py-1 rounded-lg border border-gray-200 text-slate-500 hover:text-slate-600 hover:border-gray-200 disabled:opacity-30 transition-all">
                    上一页
                  </button>
                  <span className="text-[10px] text-slate-400 tabular-nums">{page} / {totalPages}</span>
                  <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                    className="text-[10px] px-3 py-1 rounded-lg border border-gray-200 text-slate-500 hover:text-slate-600 hover:border-gray-200 disabled:opacity-30 transition-all">
                    下一页
                  </button>
                </div>
              )}
            </div>
          </section>

          {/* 右侧详情面板 */}
          <aside className="w-72 border-l border-gray-200 flex-shrink-0 overflow-y-auto bg-slate-50 hidden lg:block">
            <div className="p-4 space-y-4">
              {/* 当前域信息 */}
              <div className={`${currentTab.bg} rounded-xl p-3 border ${currentTab.border}`}>
                <div className="flex items-center gap-2 mb-2">
                  {(() => { const Ic = currentTab.icon; return <Ic size={14} className={currentTab.color} /> })()}
                  <span className={`text-xs font-semibold ${currentTab.color}`}>{currentTab.label}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-center">
                  <div><div className="text-sm font-bold text-slate-800">{total.toLocaleString()}</div><div className="text-[9px] text-slate-400">条记录</div></div>
                  <div><div className="text-sm font-bold text-slate-800">{categories.length - 1}</div><div className="text-[9px] text-slate-400">个分类</div></div>
                </div>
              </div>

              {/* 选中项预览 */}
              {selectedItem ? (
                <div className="pt-3 border-t border-gray-200">
                  <div className="flex items-center justify-between mb-2.5">
                    <h4 className="text-[11px] font-semibold text-slate-600">选中内容</h4>
                    <button onClick={() => setSelectedItem(null)} className="text-slate-400 hover:text-slate-600 transition-colors">
                      <X size={12} />
                    </button>
                  </div>
                  <div className="rounded-xl bg-slate-50 border border-gray-200 p-3 space-y-2.5">
                    {(() => {
                      const fields = getDetailFields(selectedItem, activeDomain)
                      return (
                        <>
                          <h3 className="text-[11px] font-semibold text-slate-800 line-clamp-2">{fields.title}</h3>
                          <div className="flex flex-wrap gap-1">
                            {fields.tags.map((tag, i) => (
                              <span key={i} className={`text-[9px] px-1.5 py-px rounded-full ${
                                tag.type === 'primary' ? 'bg-blue-400/10 text-blue-400' :
                                tag.type === 'success' ? 'bg-green-400/10 text-green-400' :
                                tag.type === 'warning' ? 'bg-amber-400/10 text-amber-400' :
                                'bg-slate-50 text-slate-500'
                              }`}>{tag.label}</span>
                            ))}
                          </div>
                          {fields.content && (
                            <p className="text-[10px] text-slate-500 leading-relaxed line-clamp-4">{fields.content}</p>
                          )}
                          <button onClick={() => setSelectedItem(selectedItem)}
                            className="w-full text-[10px] text-blue-400 hover:text-blue-300 py-1.5 rounded-lg border border-blue-400/15 hover:border-blue-400/30 transition-all">
                            查看完整详情
                          </button>
                        </>
                      )
                    })()}
                  </div>
                </div>
              ) : (
                /* 快捷入口 */
                <div className="pt-3 border-t border-gray-200">
                  <h4 className="text-[11px] font-semibold text-slate-600 mb-2.5 flex items-center gap-1.5">
                    <Zap size={12} className="text-amber-400" /> 常用检索
                  </h4>
                  <div className="space-y-1.5">
                    {(activeDomain === 'law' ? [
                      { title: '民法典总则编', desc: '民事主体与权利能力' },
                      { title: '合同编通则', desc: '订立·履行·违约责任' },
                      { title: '侵权责任编', desc: '归责原则与赔偿范围' },
                      { title: '婚姻家庭编', desc: '结婚·离婚·财产分割' },
                    ] : activeDomain === 'judge' ? [
                      { title: '民间借贷纠纷', desc: '借款合同·利息·担保' },
                      { title: '故意伤害罪', desc: '量刑标准·赔偿·缓刑' },
                      { title: '劳动争议', desc: '工资·解雇·工伤认定' },
                      { title: '房屋买卖纠纷', desc: '违约·交房·产权登记' },
                    ] : [
                      { title: '无罪辩护策略', desc: '证据不足·程序违法' },
                      { title: '合同抗辩策略', desc: '不可抗力·情势变更' },
                      { title: '劳动仲裁策略', desc: '经济补偿·违法解除' },
                      { title: '侵权抗辩策略', desc: '过错相抵·诉讼时效' },
                    ]).map((item, i) => (
                      <button key={i} onClick={() => { setSearchQuery(item.title); handleSearch(item.title) }}
                        className="w-full flex items-start gap-2 p-2.5 rounded-lg hover:bg-slate-50 text-left group transition-all">
                        <Hash size={11} className="text-blue-400/50 mt-0.5 flex-shrink-0 group-hover:text-blue-400" />
                        <div className="min-w-0 flex-1">
                          <span className="text-[11px] text-slate-600 group-hover:text-slate-800 truncate block">{item.title}</span>
                          <span className="text-[9px] text-slate-300 line-clamp-1">{item.desc}</span>
                        </div>
                        <ChevronRight size={10} className="text-slate-200 mt-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 更新时间 */}
              <div className="pt-3 border-t border-gray-200">
                <div className="flex items-center gap-2 text-[10px] text-slate-400">
                  <Calendar size={10} />
                  <span>数据已持久化存储</span>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </main>

      {/* 详情模态框 */}
      <DetailModal item={selectedItem} domain={activeDomain} onClose={() => setSelectedItem(null)} />

      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}

/* ========== 列表项渲染 ========== */

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
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Scale size={14} className="text-blue-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <h3 className="text-[11px] font-semibold text-slate-800 group-hover:text-blue-300 truncate">{row.law_name || '未知法规'}</h3>
          <span className="text-[9px] px-1.5 py-px rounded-full bg-blue-400/10 text-blue-400 flex-shrink-0">{row.law_type || '未分类'}</span>
          {row.article_number && <span className="text-[9px] px-1.5 py-px rounded-full bg-purple-400/10 text-purple-400 flex-shrink-0">第{row.article_number}条</span>}
        </div>
        {row.article_title && <p className="text-[10px] text-slate-400 mb-1 truncate">{row.article_title}</p>}
        <p className="text-[10px] text-slate-400 leading-relaxed line-clamp-2">{row.content || '暂无内容'}</p>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          {row.chapter && <span className="text-[9px] text-slate-300">{row.chapter}</span>}
          {row.effective_date && <span className="text-[9px] text-slate-300">{String(row.effective_date)}</span>}
          {row.status && <span className="text-[9px] text-slate-300">{String(row.status)}</span>}
        </div>
      </div>
      <ChevronRight size={13} className="text-slate-200 group-hover:text-blue-500 flex-shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-all" />
    </div>
  )
}

function renderJudgeItem(row: ListItemWithId) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Gavel size={14} className="text-emerald-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <h3 className="text-[11px] font-semibold text-slate-800 group-hover:text-emerald-300 truncate">{row.case_name || '未知案例'}</h3>
          <span className="text-[9px] px-1.5 py-px rounded-full bg-emerald-400/10 text-emerald-400 flex-shrink-0">{row.case_type || '未分类'}</span>
        </div>
        {row.cause_of_action && <p className="text-[10px] text-slate-400 mb-1 truncate">案由：{row.cause_of_action}</p>}
        {row.judgment_result && <p className="text-[10px] text-slate-400 leading-relaxed line-clamp-2">{row.judgment_result}</p>}
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          {row.case_number && <span className="text-[9px] text-slate-300">{String(row.case_number)}</span>}
          {row.court_name && <span className="text-[9px] text-slate-300">{String(row.court_name)}</span>}
          {row.judgment_date && <span className="text-[9px] text-slate-300">{String(row.judgment_date)}</span>}
        </div>
      </div>
      <ChevronRight size={13} className="text-slate-200 group-hover:text-blue-500 flex-shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-all" />
    </div>
  )
}

function renderLawyerItem(row: ListItemWithId) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-lg bg-orange-50 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Shield size={14} className="text-orange-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <h3 className="text-[11px] font-semibold text-slate-800 group-hover:text-orange-300 truncate">{row.strategy_name || '未知策略'}</h3>
          <span className="text-[9px] px-1.5 py-px rounded-full bg-orange-400/10 text-orange-400 flex-shrink-0">{row.case_type || '未分类'}</span>
          {row.success_rate != null && row.success_rate !== undefined &&
            <span className="text-[9px] px-1.5 py-px rounded-full bg-green-400/10 text-green-400 flex-shrink-0">成功率{row.success_rate}%</span>}
        </div>
        {row.applicable_scenario && <p className="text-[10px] text-slate-400 mb-1 truncate">适用场景：{row.applicable_scenario}</p>}
        {row.argument_template && <p className="text-[10px] text-slate-400 leading-relaxed line-clamp-2">{row.argument_template}</p>}
      </div>
      <ChevronRight size={13} className="text-slate-200 group-hover:text-blue-500 flex-shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-all" />
    </div>
  )
}

function renderSearchItem(result: SearchResultItem) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Search size={14} className="text-blue-600" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <h3 className="text-[11px] font-semibold text-slate-800 group-hover:text-blue-500 truncate">{result.source || '检索结果'}</h3>
          <span className="text-[9px] px-1.5 py-px rounded-full bg-blue-50 text-blue-600 flex-shrink-0">{result.doc_type || result.domain || '法律'}</span>
          {result.score > 0 && <span className="text-[9px] px-1.5 py-px rounded-full bg-green-400/10 text-green-400 flex-shrink-0">{(result.score * 100).toFixed(0)}%匹配</span>}
        </div>
        <p className="text-[10px] text-slate-400 leading-relaxed line-clamp-3">{result.content || '暂无内容'}</p>
      </div>
      <ChevronRight size={13} className="text-slate-200 group-hover:text-blue-500 flex-shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-all" />
    </div>
  )
}
