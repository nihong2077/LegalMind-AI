'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Scale, Trash2, Search, FileText, Clock, Gavel,
  FolderOpen, Play, AlertCircle, FileCheck
} from 'lucide-react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'

// 共享的存储键（与 court/page.tsx 一致）
const COURT_CASES_KEY = 'legalmind_court_cases'
const CHAT_HISTORY_KEY = 'legalmind_chat_history'

interface SavedCourtCase {
  id: string
  title: string
  description: string
  evidenceSummary: string
  result: { structuredSummary: unknown } | null
  createdAt: string
  updatedAt: string
}

interface ChatHistory {
  id: string
  title: string
  messages: Array<{ role: string; content: string; timestamp: string }>
  createdAt: string
}

function loadCourtCases(): SavedCourtCase[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem(COURT_CASES_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function loadChatHistories(): ChatHistory[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function deleteCourtCase(id: string): SavedCourtCase[] {
  const cases = loadCourtCases().filter(c => c.id !== id)
  localStorage.setItem(COURT_CASES_KEY, JSON.stringify(cases))
  return cases
}

function deleteChatHistory(id: string): ChatHistory[] {
  const histories = loadChatHistories().filter(h => h.id !== id)
  localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(histories))
  return histories
}

function loadContractReviews(): Array<{ id: string; title: string; description: string; createdAt: string }> {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem('legalmind_contract_reviews')
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}
interface UnifiedCase {
  id: string
  type: 'court' | 'chat' | 'contract'
  title: string
  description: string
  createdAt: string
  hasResult: boolean
  raw: SavedCourtCase | ChatHistory | Record<string, unknown>
}

export default function CasesPage() {
  const router = useRouter()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [cases, setCases] = useState<UnifiedCase[]>([])
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'court' | 'chat' | 'contract'>('all')
  const [selectedCase, setSelectedCase] = useState<UnifiedCase | null>(null)

  useEffect(() => {
    const court = loadCourtCases().map(c => ({
      id: c.id, type: 'court' as const, title: c.title,
      description: c.description.slice(0, 200),
      createdAt: c.createdAt, hasResult: !!c.result, raw: c,
    }))
    const chat = loadChatHistories().map(h => ({
      id: h.id, type: 'chat' as const, title: h.title,
      description: h.messages?.[0]?.content?.slice(0, 200) || '',
      createdAt: h.createdAt, hasResult: true, raw: h,
    }))
    const contract = loadContractReviews().map(r => ({
      id: r.id, type: 'contract' as const, title: r.title,
      description: r.description?.slice(0, 200) || '',
      createdAt: r.createdAt, hasResult: true, raw: r,
    }))
    setCases([...court, ...chat, ...contract].sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt)))
  }, [])

  const refresh = () => {
    const court = loadCourtCases().map(c => ({
      id: c.id, type: 'court' as const, title: c.title,
      description: c.description.slice(0, 200), createdAt: c.createdAt,
      hasResult: !!c.result, raw: c,
    }))
    const chat = loadChatHistories().map(h => ({
      id: h.id, type: 'chat' as const, title: h.title,
      description: h.messages?.[0]?.content?.slice(0, 200) || '',
      createdAt: h.createdAt, hasResult: true, raw: h,
    }))
    const contract = loadContractReviews().map(r => ({
      id: r.id, type: 'contract' as const, title: r.title,
      description: r.description?.slice(0, 200) || '',
      createdAt: r.createdAt, hasResult: true, raw: r,
    }))
    setCases([...court, ...chat, ...contract].sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt)))
  }

  const handleDelete = (c: UnifiedCase) => {
    if (c.type === 'court') {
      deleteCourtCase(c.id)
    } else if (c.type === 'chat') {
      deleteChatHistory(c.id)
    } else if (c.type === 'contract') {
      const raw = localStorage.getItem('legalmind_contract_reviews')
      if (raw) {
        const existing = JSON.parse(raw)
        localStorage.setItem('legalmind_contract_reviews', JSON.stringify(existing.filter((r: { id: string }) => r.id !== c.id)))
      }
    }
    refresh()
    if (selectedCase?.id === c.id) setSelectedCase(null)
  }

  const handleContinue = (c: UnifiedCase) => {
    if (c.type === 'court') {
      // 保存要恢复的案件 ID，court 页面会在挂载时读取
      localStorage.setItem('legalmind_continue_case', c.id)
      router.push('/court')
    } else if (c.type === 'contract') {
      router.push('/documents')
    } else {
      router.push('/chat')
    }
  }

  const filtered = cases.filter(c => {
    if (filter !== 'all' && c.type !== filter) return false
    if (search && !c.title.includes(search) && !c.description.includes(search)) return false
    return true
  })

  return (
    <div className="flex h-screen bg-white overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex bg-white overflow-hidden">
        {/* 左侧案件列表 */}
        <div className="w-80 border-r border-ink-200 flex flex-col flex-shrink-0 bg-white">
          <div className="p-4 flex items-center justify-between border-b border-ink-200">
            <h2 className="text-sm font-semibold text-ink-900 flex items-center gap-2 font-display">
              <FolderOpen size={16} className="text-blue-600" /> 案件记忆
            </h2>
            <span className="text-[10px] text-ink-400 font-body">{cases.length} 个案件</span>
          </div>

          <div className="px-3 py-2 border-b border-ink-200">
            <div className="relative">
              <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="搜索案件..." className="input-field !py-1.5 !pl-8 !pr-3 !text-[11px] !rounded-lg" />
            </div>
            <div className="flex gap-1 mt-2">
              {(['all', 'court', 'chat', 'contract'] as const).map(t => (
                <button key={t} onClick={() => setFilter(t)}
                  className={`flex-1 text-[10px] py-1 rounded-md transition-all font-body ${
                    filter === t
                      ? 'bg-blue-50 text-blue-600 border border-blue-200'
                      : 'text-ink-500 hover:text-ink-700 hover:bg-ink-50 border border-transparent'
                  }`}>
                  {t === 'all' ? '全部' : t === 'court' ? '庭审' : t === 'contract' ? '合同' : '对话'}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto bg-white">
            <AnimatePresence>
              {filtered.length > 0 ? (
                filtered.map(c => (
                  <motion.button key={c.id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                    onClick={() => setSelectedCase(c)}
                    className={`w-full text-left px-4 py-3 border-b border-ink-100 transition-colors hover:bg-ink-50
                      ${selectedCase?.id === c.id ? 'bg-blue-50/60 border-l-2 border-l-blue-500' : ''}`}>
                    <div className="flex items-center gap-2 mb-1">
                      {c.type === 'court'
                        ? <Gavel size={12} className="text-blue-500" />
                        : c.type === 'contract'
                        ? <FileCheck size={12} className="text-orange-500" />
                        : <FileText size={12} className="text-emerald-500" />}
                      <span className="text-[11px] font-medium text-ink-800 truncate font-body">{c.title}</span>
                      {c.hasResult && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />}
                    </div>
                    <p className="text-[10px] text-ink-500 line-clamp-2 ml-5 font-body">{c.description || '暂无描述'}</p>
                    <div className="flex items-center gap-3 mt-1.5 ml-5">
                      <span className="text-[9px] text-ink-400 flex items-center gap-1 font-body"><Clock size={8} />{new Date(c.createdAt).toLocaleDateString('zh-CN')}</span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-ink-100 text-ink-500 font-body">
                        {c.type === 'court' ? '模拟法庭' : c.type === 'contract' ? '合同审查' : '法律咨询'}
                      </span>
                    </div>
                  </motion.button>
                ))
              ) : (
                <div className="p-8 text-center">
                  <FolderOpen size={32} className="text-ink-300 mx-auto mb-3" />
                  <p className="text-xs text-ink-500 font-body">暂无案件记录</p>
                  <p className="text-[10px] text-ink-400 mt-1 font-body">开始使用模拟法庭或法律咨询后，案件将自动保存</p>
                </div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* 右侧案件详情 */}
        <div className="flex-1 overflow-y-auto bg-white">
          {selectedCase ? (
            <div className="p-8 max-w-3xl">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  {selectedCase.type === 'court'
                    ? <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center"><Gavel size={20} className="text-blue-600" /></div>
                    : selectedCase.type === 'contract'
                    ? <div className="w-10 h-10 rounded-xl bg-orange-50 flex items-center justify-center"><FileCheck size={20} className="text-orange-500" /></div>
                    : <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center"><FileText size={20} className="text-emerald-500" /></div>
                  }
                  <div>
                    <h3 className="text-base font-semibold text-ink-900 font-display">{selectedCase.title}</h3>
                    <p className="text-[10px] text-ink-400 font-body">
                      创建于 {new Date(selectedCase.createdAt).toLocaleString('zh-CN')}
                      &nbsp;·&nbsp;{selectedCase.type === 'court' ? '模拟法庭推演' : selectedCase.type === 'contract' ? '合同审查' : '法律咨询对话'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => handleContinue(selectedCase)} className="primary-btn flex items-center gap-1.5 text-xs !px-4 !py-2 !rounded-xl">
                    <Play size={12} /> 继续
                  </button>
                  <button onClick={() => handleDelete(selectedCase)} className="p-2 rounded-xl border border-red-200 text-red-500 hover:bg-red-50 hover:text-red-600 transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              <div className="space-y-6">
                <div className="glass-card-static p-5">
                  <h4 className="text-xs font-semibold text-ink-600 mb-3 flex items-center gap-2 font-body">
                    <FileText size={12} className="text-blue-600" /> 案件描述
                  </h4>
                  <p className="text-xs text-ink-700 leading-relaxed whitespace-pre-wrap font-body">
                    {selectedCase.description || '暂无详细描述'}
                  </p>
                </div>

                {selectedCase.type === 'court' && (selectedCase.raw as SavedCourtCase).evidenceSummary && (
                  <div className="glass-card-static p-5">
                    <h4 className="text-xs font-semibold text-ink-600 mb-3 flex items-center gap-2 font-body">
                      <AlertCircle size={12} className="text-blue-600" /> 证据摘要
                    </h4>
                    <p className="text-xs text-ink-700 leading-relaxed whitespace-pre-wrap font-body">
                      {(selectedCase.raw as SavedCourtCase).evidenceSummary}
                    </p>
                  </div>
                )}

                {selectedCase.hasResult && (
                  <div className="glass-card-static p-5 border-emerald-200" style={{ borderColor: 'rgba(52, 211, 153, 0.25)' }}>
                    <h4 className="text-xs font-semibold text-ink-600 mb-3 flex items-center gap-2 font-body">
                      <Scale size={12} className="text-emerald-500" /> 推演结果
                    </h4>
                    <p className="text-xs text-emerald-600 font-body">
                      {selectedCase.type === 'court' ? '已完成模拟法庭推演，可查看完整辩论记录和分析报告' : selectedCase.type === 'contract' ? '已完成合同审查，可查看完整审查报告' : '已完成法律咨询对话'}
                    </p>
                    <span className="inline-block mt-2 tag-emerald">已完成</span>
                  </div>
                )}

                {!selectedCase.hasResult && (
                  <div className="glass-card-static p-5 border-amber-200" style={{ borderColor: 'rgba(245, 158, 11, 0.25)' }}>
                    <h4 className="text-xs font-semibold text-ink-600 mb-3 flex items-center gap-2 font-body">
                      <Clock size={12} className="text-amber-500" /> 未完成
                    </h4>
                    <p className="text-xs text-ink-500 font-body">此案件尚未完成推演，可以继续处理。</p>
                    <span className="inline-block mt-2 tag-amber">待处理</span>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center bg-white">
              <div className="text-center">
                <FolderOpen size={48} className="text-ink-300 mx-auto mb-4" />
                <p className="text-sm text-ink-500 font-body">选择左侧案件查看详情</p>
                <p className="text-xs text-ink-400 mt-2 font-body">所有模拟法庭推演和法律咨询对话自动保存</p>
              </div>
            </div>
          )}
        </div>
      </main>
      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}
