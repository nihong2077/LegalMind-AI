'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'
import {
  Scale, Play, FileText, AlertTriangle, CheckCircle, Loader2,
  StopCircle, Download,
  Clock, CircleCheck, Circle, BookOpen,
  Gavel, RefreshCw, X
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  debateStream, type DebateStreamChunk,
  type DebateStreamDone, type StructuredSummary
} from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

type FlowStatus = 'pending' | 'running' | 'done' | 'error'

interface FlowStep {
  id: string
  label: string
  status: FlowStatus
  time?: string
  node?: string
}

interface DebateMessage {
  id: string
  role: 'judge' | 'plaintiff' | 'defendant' | 'mediator'
  content: string
  node: string
  round?: number
  timestamp: Date
}

const ROLE_CONFIG = {
  judge:     { label: '法官', icon: Scale, color: '#3b82f6', bg: 'bg-blue-500/10', border: 'border-blue-400/30', text: 'text-blue-400', avatar: 'bg-blue-500' },
  plaintiff: { label: '原告律师', icon: FileText, color: '#f97316', bg: 'bg-orange-500/10', border: 'border-orange-400/30', text: 'text-orange-400', avatar: 'bg-orange-500' },
  defendant: { label: '被告律师', icon: AlertTriangle, color: '#a855f7', bg: 'bg-purple-500/10', border: 'border-purple-400/30', text: 'text-purple-400', avatar: 'bg-purple-500' },
  mediator:  { label: '调解员', icon: CheckCircle, color: '#22c55e', bg: 'bg-green-500/10', border: 'border-green-400/30', text: 'text-green-400', avatar: 'bg-green-500' },
}

const INITIAL_FLOW_STEPS: FlowStep[] = [
  { id: 'extract_kfe', label: '案情解析', status: 'pending', node: 'extract_kfe' },
  { id: 'check_evidence', label: '证据检查', status: 'pending', node: 'check_evidence' },
  { id: 'retrieve_knowledge', label: '法律检索', status: 'pending', node: 'retrieve_knowledge' },
  { id: 'judge_opening', label: '法官开庭', status: 'pending', node: 'judge_opening' },
  { id: 'plaintiff_opening', label: '原告陈述', status: 'pending', node: 'plaintiff_opening' },
  { id: 'defendant_opening', label: '被告陈述', status: 'pending', node: 'defendant_opening' },
  { id: 'court_investigation', label: '法庭调查', status: 'pending', node: 'court_investigation' },
  { id: 'debate_loop', label: '辩论循环', status: 'pending', node: 'plaintiff_rebuttal' },
  { id: 'judge_verdict', label: '法官裁决', status: 'pending', node: 'judge_verdict' },
  { id: 'judgment_report', label: '判决书生成', status: 'pending', node: 'judgment_report' },
  { id: 'finalize', label: '汇总报告', status: 'pending', node: 'finalize' },
]

const NODE_TO_STEP: Record<string, string> = {
  'extract_kfe': 'extract_kfe',
  'check_evidence': 'check_evidence',
  'retrieve_knowledge': 'retrieve_knowledge',
  'judge_opening': 'judge_opening',
  'plaintiff_opening': 'plaintiff_opening',
  'defendant_opening': 'defendant_opening',
  'court_investigation': 'court_investigation',
  'plaintiff_rebuttal': 'debate_loop',
  'defendant_rebuttal': 'debate_loop',
  'judge_comment': 'debate_loop',
  'judge_verdict': 'judge_verdict',
  'judgment_report': 'judgment_report',
  'finalize': 'finalize',
}

function detectRole(node: string): DebateMessage['role'] {
  if (node.includes('judge') || node.includes('verdict')) return 'judge'
  if (node.includes('plaintiff')) return 'plaintiff'
  if (node.includes('defendant')) return 'defendant'
  if (node.includes('mediator') || node.includes('plain_language')) return 'mediator'
  return 'judge'
}

function getPhaseLabel(node: string, round: number): string {
  const role = detectRole(node)
  const map: Record<string, string> = { judge: '法官', plaintiff: '原告律师', defendant: '被告律师', mediator: '调解员' }
  return `${map[role] || '系统'} 第${round}轮`
}

// 本地存储键
const COURT_CASES_KEY = 'legalmind_court_cases'

interface SavedCourtCase {
  id: string
  title: string
  description: string
  evidenceSummary: string
  result: SavedCourtResult | null
  createdAt: string
  updatedAt: string
}

interface SavedCourtResult {
  messages: { role: string; content: string; node: string; round?: number; timestamp: string }[]
  verdict: string
  judgmentReport: string
  plainLanguage: string
  convergenceReason: string
  kfe: Record<string, unknown>
  structuredSummary: StructuredSummary | null
}

function loadCourtCases(): SavedCourtCase[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem(COURT_CASES_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveCourtCases(cases: SavedCourtCase[]) {
  if (typeof window === 'undefined') return
  localStorage.setItem(COURT_CASES_KEY, JSON.stringify(cases.slice(0, 50)))
}

export default function CourtPage() {
  const { authed } = useChatStore()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [phase, setPhase] = useState<'input' | 'debating' | 'done'>('input')

  // 案件输入
  const [caseTitle, setCaseTitle] = useState('')
  const [caseDescription, setCaseDescription] = useState('')
  const [evidenceSummary, setEvidenceSummary] = useState('')

  // 辩论状态
  const [messages, setMessages] = useState<DebateMessage[]>([])
  const [flowSteps, setFlowSteps] = useState<FlowStep[]>(INITIAL_FLOW_STEPS.map(s => ({ ...s })))
  const [currentRound, setCurrentRound] = useState(0)
  const [currentPhaseLabel, setCurrentPhaseLabel] = useState('')
  const [confidence, setConfidence] = useState(0)
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 结果数据
  const [evidences, setEvidences] = useState<Array<{ name: string; type: string; relevance: string; conclusion: string }>>([])
  const [lawArticles, setLawArticles] = useState<Array<{ title: string; source: string; excerpt: string; relevance: string }>>([])
  const [kfeItems, setKfeItems] = useState<Array<{ label: string; value: string; status: 'verified' | 'unverified' | 'pending' }>>([])
  const [structuredReport, setStructuredReport] = useState<StructuredSummary | null>(null)
  const [canSign, setCanSign] = useState<string>('待评估')

  // 历史案件
  const [savedCases, setSavedCases] = useState<SavedCourtCase[]>([])

  const [activeRightTab, setActiveRightTab] = useState<'evidence' | 'law' | 'kfe'>('evidence')
  const [activeBottomTab, setActiveBottomTab] = useState<'report' | 'solution'>('report')
  const [roleFilter, setRoleFilter] = useState('all')
  const abortRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setSavedCases(loadCourtCases()) }, [])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const updateFlowStep = useCallback((nodeId: string, status: FlowStatus) => {
    const stepId = NODE_TO_STEP[nodeId]
    if (!stepId) return
    setFlowSteps(prev => prev.map(step =>
      step.id === stepId ? { ...step, status, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) } : step
    ))
  }, [])

  const saveCurrentCase = useCallback(() => {
    if (!caseDescription.trim()) return
    const id = Date.now().toString()
    const c: SavedCourtCase = {
      id,
      title: caseTitle || '未命名案件',
      description: caseDescription,
      evidenceSummary,
      result: phase === 'done' ? {
        messages: messages.map(m => ({ ...m, timestamp: m.timestamp.toISOString() })),
        verdict: '',
        judgmentReport: '',
        plainLanguage: '',
        convergenceReason: '',
        kfe: {},
        structuredSummary: structuredReport,
      } : null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    const updated = [c, ...savedCases]
    setSavedCases(updated)
    saveCourtCases(updated)
  }, [caseTitle, caseDescription, evidenceSummary, phase, messages, structuredReport, savedCases])

  const loadSavedCase = (c: SavedCourtCase) => {
    setCaseTitle(c.title)
    setCaseDescription(c.description)
    setEvidenceSummary(c.evidenceSummary)
    if (c.result) {
      setMessages(c.result.messages.map(m => ({
        id: Date.now().toString() + Math.random(),
        role: (m.role as DebateMessage['role']),
        content: m.content,
        node: m.node,
        round: m.round,
        timestamp: new Date(m.timestamp),
      })))
      setStructuredReport(c.result.structuredSummary)
      setPhase('done')
    } else {
      setMessages([])
      setPhase('input')
    }
    setFlowSteps(INITIAL_FLOW_STEPS.map(s => ({ ...s })))
  }

  const handleStartDebate = async () => {
    if (!caseDescription.trim()) return
    if (!authed) { setError('请先登录'); return }

    setMessages([])
    setError(null)
    setPhase('debating')
    setIsStreaming(true)
    setFlowSteps(INITIAL_FLOW_STEPS.map(s => ({ ...s, status: 'pending' as FlowStatus, time: undefined })))
    setCurrentRound(0)
    setCurrentPhaseLabel('')
    setConfidence(0)
    setEvidences([])
    setLawArticles([])
    setKfeItems([])
    setStructuredReport(null)
    setCanSign('待评估')

    const abortController = new AbortController()
    abortRef.current = abortController

    let currentRole: DebateMessage['role'] = 'judge'
    let currentContent = ''
    let currentNode = ''
    let currentRoundNum = 0

    try {
      for await (const event of debateStream({
        case_description: caseDescription,
        evidence_summary: evidenceSummary,
        task_type: 'debate',
      }, abortController.signal)) {

        if (event.type === 'chunk') {
          const chunk = event.data as DebateStreamChunk

          if (chunk.node !== currentNode) {
            if (currentContent && currentNode) {
              setMessages(prev => [...prev, {
                id: `${Date.now()}-${Math.random()}`, role: currentRole,
                content: currentContent, node: currentNode, round: currentRoundNum, timestamp: new Date(),
              }])
            }
            updateFlowStep(currentNode || chunk.node, 'done')
            updateFlowStep(chunk.node, 'running')
            currentRole = detectRole(chunk.node)
            currentContent = chunk.content
            currentNode = chunk.node
            if (chunk.node.includes('rebuttal') || chunk.node.includes('opening')) {
              currentRoundNum++
              setCurrentRound(currentRoundNum)
            }
          } else {
            currentContent += chunk.content
          }
          setCurrentPhaseLabel(getPhaseLabel(chunk.node, currentRoundNum))
          setConfidence(prev => Math.min(95, prev + Math.random() * 2))

          setMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.node === currentNode && last.role === currentRole) {
              updated[updated.length - 1] = { ...last, content: currentContent }
            } else {
              updated.push({ id: `${Date.now()}-${Math.random()}`, role: detectRole(chunk.node), content: currentContent, node: currentNode, round: currentRoundNum, timestamp: new Date() })
            }
            return updated
          })

        } else if (event.type === 'metadata') {
          const meta = event.data as { type: string; kfe?: Record<string, unknown> | null; legal_knowledge?: string | null }
          if (meta.type === 'extract_kfe' && meta.kfe) {
            const items = Object.entries(meta.kfe).map(([key, val]) => ({
              label: key, value: typeof val === 'string' ? val : JSON.stringify(val), status: 'verified' as const,
            }))
            if (items.length > 0) setKfeItems(items)
          }
          if (meta.type === 'retrieve_knowledge' && meta.legal_knowledge) {
            const lines = meta.legal_knowledge.split('\n').filter((l: string) => l.trim())
            const articles = lines.slice(0, 6).map((line: string) => ({
              title: line.split('：')[0]?.trim() || line.slice(0, 40),
              source: '法律库',
              excerpt: line.split('：')[1]?.trim() || line.slice(0, 80),
              relevance: '直接相关',
            }))
            if (articles.length > 0) setLawArticles(articles)
          }

        } else if (event.type === 'done') {
          if (currentContent && currentNode) {
            setMessages(prev => [...prev, {
              id: `${Date.now()}-${Math.random()}`, role: currentRole,
              content: currentContent, node: currentNode, round: currentRoundNum, timestamp: new Date(),
            }])
          }
          updateFlowStep(currentNode || 'finalize', 'done')
          setFlowSteps(prev => prev.map(s => ({ ...s, status: 'done' as FlowStatus })))

          const done = event.data as DebateStreamDone
          const summary = done.structured_summary

          if (summary) {
            setStructuredReport(summary)
            if (summary.kfe_items?.length) setKfeItems(summary.kfe_items)
            if (summary.law_articles?.length) setLawArticles(summary.law_articles)
            if (summary.evidence_analysis?.length) setEvidences(summary.evidence_analysis.map(e => ({ name: e.name, type: e.type, relevance: e.relevance, conclusion: e.conclusion })))
            if (summary.confidence_score) setConfidence(summary.confidence_score)
            if (summary.can_sign) setCanSign(summary.can_sign)
          }

          setPhase('done')
          saveCurrentCase()  // 辩论完成后自动保存案件
        } else if (event.type === 'error') {
          const err = event.data as { error: string; message: string }
          setError(err.message || '辩论服务暂时不可用')
          setPhase('done')
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError(`辩论过程出错: ${(e as Error).message}`)
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }

  const handleStop = () => {
    if (abortRef.current) { abortRef.current.abort(); setIsStreaming(false); setPhase('done') }
  }

  const handleReset = () => {
    setCaseTitle(''); setCaseDescription(''); setEvidenceSummary('')
    setMessages([])
    setFlowSteps(INITIAL_FLOW_STEPS.map(s => ({ ...s, status: 'pending' as FlowStatus, time: undefined })))
    setCurrentRound(0); setCurrentPhaseLabel(''); setConfidence(0); setPhase('input'); setError(null)
    setEvidences([]); setLawArticles([]); setKfeItems([]); setStructuredReport(null); setCanSign('待评估')
  }

  const handleExportReport = () => {
    const content = structuredReport
      ? JSON.stringify(structuredReport, null, 2)
      : messages.map(m => `[${ROLE_CONFIG[m.role].label}] ${m.content}`).join('\n\n') || '暂无报告内容'
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `法庭报告_${new Date().toISOString().slice(0,10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const flowIcon = (status: FlowStatus) => {
    switch (status) {
      case 'running': return <Loader2 size={14} className="text-blue-400 animate-spin" />
      case 'done': return <CircleCheck size={14} className="text-green-400" />
      case 'error': return <X size={14} className="text-red-400" />
      default: return <Circle size={14} className="text-gold-200/30" />
    }
  }

  const CAN_SIGN_STYLE: Record<string, { bg: string; text: string; label: string }> = {
    '可签': { bg: 'bg-green-500/10', text: 'text-green-400', label: '可签' },
    '有条件可签': { bg: 'bg-yellow-500/10', text: 'text-yellow-400', label: '有条件可签' },
    '不建议签': { bg: 'bg-red-500/10', text: 'text-red-400', label: '不建议签' },
    '待评估': { bg: 'bg-gray-500/10', text: 'text-gray-400', label: '待评估' },
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex flex-col bg-[#0a1628] overflow-hidden">
        {/* 顶部标题栏 */}
        <div className="h-14 border-b border-white/5 flex items-center justify-between px-6 bg-[#0d1a2d]/80 backdrop-blur-sm flex-shrink-0">
          <div className="flex items-center gap-3">
            <Gavel size={20} className="text-blue-400" />
            <h1 className="text-base font-semibold text-gold-200">{caseTitle || '模拟法庭推演'}</h1>
            {phase !== 'input' && (
              <>
                <span className="text-gold-200/40">|</span>
                <span className="text-xs text-gold-200/60">
                  当前阶段：<span className="text-blue-400 font-medium">{currentPhaseLabel || '准备中'}</span>
                  {currentRound > 0 && <span className="ml-1">（第{currentRound}轮）</span>}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            {phase !== 'input' && canSign !== '待评估' && (
              <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border ${CAN_SIGN_STYLE[canSign].bg} ${CAN_SIGN_STYLE[canSign].text.replace('text-', 'border-')}`}>
                <div className={`w-2 h-2 rounded-full ${canSign === '可签' ? 'bg-green-400' : canSign === '不建议签' ? 'bg-red-400' : 'bg-yellow-400'}`} />
                <span className="text-xs font-medium">{CAN_SIGN_STYLE[canSign].label}</span>
                <span className="text-[10px] opacity-70 ml-1">置信度 {confidence}%</span>
              </div>
            )}
            <button onClick={handleExportReport} disabled={phase === 'input'} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gold-400/10 border border-gold-400/25 text-gold-300 text-xs hover:bg-gold-400/20 transition-colors disabled:opacity-30"><Download size={12} /> 导出报告</button>
          </div>
        </div>

        {/* 主内容区 */}
        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：推演流程 */}
          <aside className="w-56 border-r border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/50">
            <div className="p-4">
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/5">
                <div className="flex items-center gap-2"><Clock size={14} className="text-blue-400" /><span className="text-xs font-medium text-gold-200/70">推演流程</span></div>
              </div>

              {/* 历史案件 */}
              {savedCases.length > 0 && phase === 'input' && (
                <>
                  <div className="mb-3">
                    <h4 className="text-[10px] text-gold-200/40 mb-2">历史案件</h4>
                    <div className="space-y-1 max-h-40 overflow-y-auto">
                      {savedCases.slice(0, 5).map(c => (
                        <button key={c.id} onClick={() => loadSavedCase(c)}
                          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-white/[0.03] transition-colors group">
                          <p className="text-[11px] text-gold-200/60 truncate group-hover:text-gold-200/80">{c.title}</p>
                          <p className="text-[9px] text-gold-200/25">{new Date(c.createdAt).toLocaleDateString('zh-CN')}</p>
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="border-t border-white/5 mb-4" />
                </>
              )}

              <div className="space-y-0.5">
                {flowSteps.map((step) => (
                  <motion.div key={step.id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                    className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-xs cursor-default transition-all ${
                      step.status === 'running' ? 'bg-blue-500/10 border border-blue-400/20' : step.status === 'done' ? 'hover:bg-white/5' : 'opacity-50'
                    }`}>
                    {flowIcon(step.status)}
                    <span className={`flex-1 truncate ${step.status === 'running' ? 'text-blue-400 font-medium' : step.status === 'done' ? 'text-gold-200/70' : 'text-gold-200/40'}`}>{step.label}</span>
                    {step.time && <span className="text-[10px] text-gold-200/25">{step.time}</span>}
                  </motion.div>
                ))}
              </div>
            </div>
          </aside>

          {/* 中间区域 */}
          <section className="flex-1 flex flex-col overflow-hidden min-w-0">
            {phase === 'input' ? (
              /* 案件输入表单 */
              <div className="flex-1 overflow-y-auto p-8 flex items-center justify-center">
                <div className="w-full max-w-2xl space-y-6">
                  <div className="text-center mb-2">
                    <Gavel size={36} className="text-blue-400 mx-auto mb-3" />
                    <h2 className="text-xl font-bold text-gold-200">模拟法庭推演</h2>
                    <p className="text-sm text-gold-200/40 mt-1">输入案件信息，启动多智能体庭审辩论</p>
                  </div>

                  <div>
                    <label className="text-xs text-gold-200/60 mb-1.5 block">案件标题</label>
                    <input value={caseTitle} onChange={e => setCaseTitle(e.target.value)}
                      placeholder="例：民间借贷纠纷案"
                      className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-3 text-sm text-gold-200 placeholder:text-gold-200/25 focus:outline-none focus:border-blue-400/40 transition-all" />
                  </div>

                  <div>
                    <label className="text-xs text-gold-200/60 mb-1.5 block">案件描述 <span className="text-red-400">*</span></label>
                    <textarea value={caseDescription} onChange={e => setCaseDescription(e.target.value)}
                      placeholder="请详细描述案件事实、当事人关系、争议内容..."
                      rows={6}
                      className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-3 text-sm text-gold-200 placeholder:text-gold-200/25 focus:outline-none focus:border-blue-400/40 transition-all resize-none" />
                  </div>

                  <div>
                    <label className="text-xs text-gold-200/60 mb-1.5 block">证据摘要（可选）</label>
                    <textarea value={evidenceSummary} onChange={e => setEvidenceSummary(e.target.value)}
                      placeholder="列举案件相关证据材料..."
                      rows={3}
                      className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-3 text-sm text-gold-200 placeholder:text-gold-200/25 focus:outline-none focus:border-blue-400/40 transition-all resize-none" />
                  </div>

                  <button onClick={handleStartDebate} disabled={!caseDescription.trim()}
                    className="w-full gold-btn py-3 flex items-center justify-center gap-2 text-base disabled:opacity-40">
                    <Play size={18} /> 开始庭审推演
                  </button>
                </div>
              </div>
            ) : (
              /* 辩论进行中/完成 */
              <>
                <div className="h-11 border-b border-white/5 flex items-center justify-between px-4 flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gold-200/60"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/></svg>
                    <span className="text-xs font-medium text-gold-200/70">庭审推演（多智能体协同）</span>
                  </div>
                  <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} className="text-[10px] bg-transparent border border-white/10 rounded px-2 py-1 text-gold-200/50 focus:outline-none focus:border-gold-400/30">
                    <option value="all">显示全部</option>
                    <option value="judge">仅法官</option>
                    <option value="lawyer">仅律师</option>
                  </select>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                  {error && <div className="p-3 rounded-lg bg-red-400/10 border border-red-400/20 text-red-400 text-xs">{error}</div>}
                  <AnimatePresence>
                    {messages.filter(msg => {
                      if (roleFilter === 'all') return true
                      if (roleFilter === 'judge') return msg.role === 'judge'
                      if (roleFilter === 'lawyer') return msg.role === 'plaintiff' || msg.role === 'defendant'
                      return true
                    }).map((msg) => {
                      const config = ROLE_CONFIG[msg.role]; const IconComp = config.icon
                      return (
                        <motion.div key={msg.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className={`rounded-xl ${config.bg} border ${config.border} p-4`}>
                          <div className="flex items-start gap-3">
                            <div className={`w-9 h-9 rounded-full ${config.avatar} flex items-center justify-center flex-shrink-0`}><IconComp size={16} className="text-white" /></div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1.5">
                                <span className={`text-sm font-semibold ${config.text}`}>{config.label}</span>
                                {msg.round && <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-gold-200/50">第{msg.round}轮</span>}
                                <span className="text-[10px] text-gold-200/30 ml-auto">{msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                              </div>
                              <div className="text-xs text-gold-200/75 leading-relaxed whitespace-pre-wrap">{msg.content}</div>
                            </div>
                          </div>
                        </motion.div>
                      )
                    })}
                  </AnimatePresence>
                  {isStreaming && messages.length === 0 && (
                    <div className="flex items-center justify-center py-20">
                      <div className="flex items-center gap-3 text-gold-200/40"><Loader2 size={20} className="animate-spin text-blue-400" /><span className="text-sm">正在分析案情，提取关键法律事实...</span></div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>

                <div className="h-11 border-t border-white/5 flex items-center justify-between px-4 flex-shrink-0 bg-[#0c1729]/80">
                  <div className="flex items-center gap-2">
                    {isStreaming && (<button onClick={handleStop} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-400/30 text-red-400 text-xs hover:bg-red-400/10"><StopCircle size={12} /> 停止推演</button>)}
                    {phase === 'done' && !isStreaming && (<button onClick={handleReset} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gold-400/25 text-gold-300 text-xs hover:bg-gold-400/10"><RefreshCw size={12} /> 新案件</button>)}
                  </div>
                </div>
              </>
            )}
          </section>

          {/* 右侧信息面板 */}
          <aside className="w-72 border-l border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/50">
            <div className="p-4">
              <div className="flex items-center gap-1 mb-4 p-1 rounded-lg bg-white/5">
                {(['evidence', 'law', 'kfe'] as const).map(tab => (
                  <button key={tab} onClick={() => setActiveRightTab(tab)} className={`flex-1 text-[11px] py-1.5 rounded-md transition-all font-medium ${activeRightTab === tab ? 'bg-blue-500/20 text-blue-400 shadow-sm' : 'text-gold-200/45 hover:text-gold-200/70'}`}>
                    {tab === 'evidence' ? '证据' : tab === 'law' ? '法条' : 'KFE'}
                  </button>
                ))}
              </div>

              {activeRightTab === 'evidence' && (
                <div className="space-y-3">
                  <span className="text-xs font-medium text-gold-200/70">证据分析 ({evidences.length})</span>
                  {evidences.length > 0 ? (
                    <div className="space-y-2">
                      {evidences.map((ev, i) => (
                        <div key={i} className="rounded-lg bg-white/[0.03] border border-white/5 p-2.5">
                          <div className="flex items-start gap-2">
                            <FileText size={12} className="text-blue-400 mt-0.5" />
                            <div>
                              <p className="text-[11px] text-gold-200/80">{ev.name}</p>
                              <p className="text-[9px] text-gold-200/30">{ev.relevance} · {ev.conclusion?.slice(0, 30)}</p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gold-200/30 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '等待证据分析完成...'}</p>
                  )}
                </div>
              )}

              {activeRightTab === 'law' && (
                <div className="space-y-3">
                  <span className="text-xs font-medium text-gold-200/70">引用法条 ({lawArticles.length})</span>
                  {lawArticles.length > 0 ? (
                    <div className="space-y-2">
                      {lawArticles.map((a, i) => (
                        <div key={i} className="rounded-lg bg-blue-500/5 border border-blue-400/10 p-2.5">
                          <div className="flex items-center gap-1.5 mb-1"><BookOpen size={10} className="text-blue-400/60" /><span className="text-[10px] text-blue-400/90 font-medium line-clamp-1">{a.title}</span></div>
                          <p className="text-[10px] text-gold-200/45 leading-relaxed line-clamp-2">{a.excerpt}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gold-200/30 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '辩论中自动检索...'}</p>
                  )}
                </div>
              )}

              {activeRightTab === 'kfe' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-gold-200/70">KFE 关键要素</span>
                  </div>
                  {kfeItems.length > 0 ? (
                    <div className="space-y-2">
                      {kfeItems.map((item, i) => (
                        <div key={i} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-white/[0.02]">
                          <span className="text-[11px] text-gold-200/55 w-16 flex-shrink-0">{item.label}</span>
                          <span className="text-[11px] text-gold-200/75 truncate">{item.value}</span>
                          <span className={`text-[10px] flex-shrink-0 ml-2 ${item.status === 'verified' ? 'text-green-400' : item.status === 'unverified' ? 'text-red-400' : 'text-gold-200/30'}`}>
                            {item.status === 'verified' ? '已收敛' : item.status === 'unverified' ? '未收敛' : '待检测'}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gold-200/30 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '正在提取关键法律事实...'}</p>
                  )}
                </div>
              )}
            </div>
          </aside>
        </div>

        {/* 底部报告区 */}
        {messages.length > 0 && (
          <div className="h-52 border-t border-white/5 bg-[#0c1729]/80 flex-shrink-0">
            <div className="h-full flex flex-col">
              <div className="h-10 border-b border-white/5 flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2"><FileText size={14} className="text-gold-200/60" /><span className="text-xs font-medium text-gold-200/70">分析报告</span></div>
                <div className="flex items-center gap-3">
                  <button onClick={() => setActiveBottomTab('report')} className={`text-[11px] px-3 py-1 rounded transition-all ${activeBottomTab === 'report' ? 'text-blue-400 bg-blue-500/15' : 'text-gold-200/40 hover:text-gold-200/60'}`}>案件分析</button>
                  <button onClick={() => setActiveBottomTab('solution')} className={`text-[11px] px-3 py-1 rounded transition-all ${activeBottomTab === 'solution' ? 'text-blue-400 bg-blue-500/15' : 'text-gold-200/40 hover:text-gold-200/60'}`}>调解方案</button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-4">
                {structuredReport ? (
                  activeBottomTab === 'report' ? (
                    <div className="grid grid-cols-4 gap-4 h-full">
                      {[
                        { key: 'case_analysis' as const, title: '案情分析', num: '一' },
                        { key: 'fact_finding' as const, title: '事实认定', num: '二' },
                        { key: 'legal_application' as const, title: '法律适用', num: '三' },
                        { key: 'conclusion' as const, title: '裁判结论', num: '四' },
                      ].map(sec => (
                        <div key={sec.key} className="space-y-2">
                          <h4 className="text-[11px] font-semibold text-gold-200/80 flex items-center gap-1.5">
                            <span className="w-4 h-4 rounded bg-blue-500/20 text-blue-400 flex items-center justify-center text-[9px]">{sec.num}</span>{sec.title}
                          </h4>
                          <ul className="space-y-1.5 pl-5">
                            {(structuredReport.report_sections?.[sec.key] || ['等待生成...']).map((item, i) => (
                              <li key={i} className="text-[10px] text-gold-200/60 list-disc">{item}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-4 h-full">
                      <div className="border border-white/5 rounded-lg p-3">
                        <h4 className="text-[11px] font-semibold text-gold-200/80 mb-2">调解方案草案</h4>
                        <p className="text-[10px] text-gold-200/60 leading-relaxed whitespace-pre-wrap">{structuredReport.mediation_suggestion?.draft || '基于庭审辩论结果，建议双方就争议焦点达成谅解...'}</p>
                      </div>
                      <div className="border border-white/5 rounded-lg p-3">
                        <h4 className="text-[11px] font-semibold text-gold-200/80 mb-2">执行保障措施</h4>
                        <p className="text-[10px] text-gold-200/60 leading-relaxed whitespace-pre-wrap">{structuredReport.mediation_suggestion?.enforcement || '为确保调解协议得到有效执行，建议采取以下保障措施...'}</p>
                      </div>
                    </div>
                  )
                ) : (
                  <div className="flex items-center justify-center h-full text-[11px] text-gold-200/35">
                    {isStreaming ? '等待辩论完成后自动生成结构化报告...' : '暂无报告数据'}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </main>
      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}