'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Scale, Trash2, Search, FileText, Clock, Gavel,
  ChevronRight, FolderOpen, Play, AlertCircle, Loader2, ArrowLeft
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

// 统一案件条目
interface UnifiedCase {
  id: string
  type: 'court' | 'chat'
  title: string
  description: string
  createdAt: string
  hasResult: boolean
  raw: SavedCourtCase | ChatHistory
}

export default function CasesPage() {
  const router = useRouter()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [cases, setCases] = useState<UnifiedCase[]>([])
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'court' | 'chat'>('all')
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
    setCases([...court, ...chat].sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt)))
  }, [])

  const refresh = () => {
    setCases(prev => {
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
      return [...court, ...chat].sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt))
    })
  }

  const handleDelete = (c: UnifiedCase) => {
    if (c.type === 'court') {
      deleteCourtCase(c.id)
    } else {
      deleteChatHistory(c.id)
    }
    refresh()
    if (selectedCase?.id === c.id) setSelectedCase(null)
  }

  const handleContinue = (c: UnifiedCase) => {
    if (c.type === 'court') {
      router.push('/court')
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
    <div className="flex h-screen overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex bg-[#0a1628] overflow-hidden">
        {/* 左侧案件列表 */}
        <div className="w-80 border-r border-white/5 flex flex-col flex-shrink-0 bg-[#0c1729]/50">
          <div className="p-4 flex items-center justify-between border-b border-white/5">
            <h2 className="text-sm font-semibold text-gold-200 flex items-center gap-2">
              <FolderOpen size={16} className="text-blue-400" /> 案件记忆
            </h2>
            <span className="text-[10px] text-gold-200/30">{cases.length} 个案件</span>
          </div>

          <div className="px-3 py-2 border-b border-white/5">
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gold-200/30" />
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="搜索案件..." className="w-full bg-white/[0.03] border border-white/10 rounded-lg pl-7 pr-3 py-1.5 text-[11px] text-gold-200 placeholder:text-gold-200/25 focus:outline-none focus:border-blue-400/40" />
            </div>
            <div className="flex gap-1 mt-2">
              {(['all', 'court', 'chat'] as const).map(t => (
                <button key={t} onClick={() => setFilter(t)}
                  className={`flex-1 text-[10px] py-1 rounded-md transition-all ${filter === t ? 'bg-blue-500/20 text-blue-400' : 'text-gold-200/40 hover:text-gold-200/60'}`}>
                  {t === 'all' ? '全部' : t === 'court' ? '庭审' : '对话'}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            <AnimatePresence>
              {filtered.length > 0 ? (
                filtered.map(c => (
                  <motion.button key={c.id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                    onClick={() => setSelectedCase(c)}
                    className={`w-full text-left px-4 py-3 border-b border-white/[0.03] transition-colors hover:bg-white/[0.02]
                      ${selectedCase?.id === c.id ? 'bg-blue-500/5 border-l-2 border-l-blue-400' : ''}`}>
                    <div className="flex items-center gap-2 mb-1">
                      {c.type === 'court' ? <Gavel size={12} className="text-blue-400" /> : <FileText size={12} className="text-green-400" />}
                      <span className="text-[11px] font-medium text-gold-200/80 truncate">{c.title}</span>
                      {c.hasResult && <span className="w-1.5 h-1.5 rounded-full bg-green-400 flex-shrink-0" />}
                    </div>
                    <p className="text-[10px] text-gold-200/35 line-clamp-2 ml-5">{c.description || '暂无描述'}</p>
                    <div className="flex items-center gap-3 mt-1.5 ml-5">
                      <span className="text-[9px] text-gold-200/25 flex items-center gap-1"><Clock size={8} />{new Date(c.createdAt).toLocaleDateString('zh-CN')}</span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-gold-200/30">
                        {c.type === 'court' ? '模拟法庭' : '法律咨询'}
                      </span>
                    </div>
                  </motion.button>
                ))
              ) : (
                <div className="p-8 text-center">
                  <FolderOpen size={32} className="text-gold-200/15 mx-auto mb-3" />
                  <p className="text-xs text-gold-200/30">暂无案件记录</p>
                  <p className="text-[10px] text-gold-200/20 mt-1">开始使用模拟法庭或法律咨询后，案件将自动保存</p>
                </div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* 右侧案件详情 */}
        <div className="flex-1 overflow-y-auto">
          {selectedCase ? (
            <div className="p-8 max-w-3xl">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  {selectedCase.type === 'court'
                    ? <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center"><Gavel size={20} className="text-blue-400" /></div>
                    : <div className="w-10 h-10 rounded-xl bg-green-500/10 flex items-center justify-center"><FileText size={20} className="text-green-400" /></div>
                  }
                  <div>
                    <h3 className="text-base font-semibold text-gold-200">{selectedCase.title}</h3>
                    <p className="text-[10px] text-gold-200/30">
                      创建于 {new Date(selectedCase.createdAt).toLocaleString('zh-CN')}
                      &nbsp;·&nbsp;{selectedCase.type === 'court' ? '模拟法庭推演' : '法律咨询对话'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => handleContinue(selectedCase)} className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 text-white text-xs hover:bg-blue-700 transition-colors">
                    <Play size={12} /> 继续
                  </button>
                  <button onClick={() => handleDelete(selectedCase)} className="p-2 rounded-xl border border-red-400/20 text-red-400/60 hover:bg-red-400/10 hover:text-red-400 transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              <div className="space-y-6">
                <div className="rounded-xl border border-white/5 bg-white/[0.01] p-5">
                  <h4 className="text-xs font-semibold text-gold-200/70 mb-3 flex items-center gap-2">
                    <FileText size={12} className="text-blue-400" /> 案件描述
                  </h4>
                  <p className="text-xs text-gold-200/60 leading-relaxed whitespace-pre-wrap">
                    {selectedCase.description || '暂无详细描述'}
                  </p>
                </div>

                {selectedCase.type === 'court' && (selectedCase.raw as SavedCourtCase).evidenceSummary && (
                  <div className="rounded-xl border border-white/5 bg-white/[0.01] p-5">
                    <h4 className="text-xs font-semibold text-gold-200/70 mb-3 flex items-center gap-2">
                      <AlertCircle size={12} className="text-yellow-400" /> 证据摘要
                    </h4>
                    <p className="text-xs text-gold-200/60 leading-relaxed whitespace-pre-wrap">
                      {(selectedCase.raw as SavedCourtCase).evidenceSummary}
                    </p>
                  </div>
                )}

                {selectedCase.hasResult && (
                  <div className="rounded-xl border border-green-400/10 bg-green-500/[0.02] p-5">
                    <h4 className="text-xs font-semibold text-gold-200/70 mb-3 flex items-center gap-2">
                      <Scale size={12} className="text-green-400" /> 推演结果
                    </h4>
                    <p className="text-xs text-green-400/70">
                      {selectedCase.type === 'court' ? '已完成模拟法庭推演，可查看完整辩论记录和分析报告' : '已完成法律咨询对话'}
                    </p>
                  </div>
                )}

                {!selectedCase.hasResult && (
                  <div className="rounded-xl border border-yellow-400/10 bg-yellow-500/[0.02] p-5">
                    <h4 className="text-xs font-semibold text-gold-200/70 mb-3 flex items-center gap-2">
                      <Clock size={12} className="text-yellow-400" /> 未完成
                    </h4>
                    <p className="text-xs text-gold-200/40">此案件尚未完成推演，可以继续处理。</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                <FolderOpen size={48} className="text-gold-200/10 mx-auto mb-4" />
                <p className="text-sm text-gold-200/30">选择左侧案件查看详情</p>
                <p className="text-xs text-gold-200/20 mt-2">所有模拟法庭推演和法律咨询对话自动保存</p>
              </div>
            </div>
          )}
        </div>
      </main>
      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}