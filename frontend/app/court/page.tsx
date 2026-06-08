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
  judge:     { label: '法官', icon: Scale, color: '#e6be44', bg: 'bg-navy-800/50', border: 'border-gold-400/20', text: 'text-gold-300', avatar: 'bg-gold-400/20' },
  plaintiff: { label: '原告律师', icon: FileText, color: '#fdba74', bg: 'bg-orange-900/20', border: 'border-orange-400/20', text: 'text-orange-300', avatar: 'bg-orange-500/30' },
  defendant: { label: '被告律师', icon: AlertTriangle, color: '#c4b5fd', bg: 'bg-purple-900/20', border: 'border-purple-400/20', text: 'text-purple-300', avatar: 'bg-purple-500/30' },
  mediator:  { label: '调解员', icon: CheckCircle, color: '#6ee7b7', bg: 'bg-emerald-900/20', border: 'border-emerald-400/20', text: 'text-emerald-300', avatar: 'bg-emerald-500/30' },
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
  if (!node) return 'judge'
  if (node.includes('plaintiff')) return 'plaintiff'
  if (node.includes('defendant')) return 'defendant'
  if (node.includes('mediator') || node.includes('plain_language')) return 'mediator'
  // judge_opening, judge_comment, judge_verdict, court_investigation, judgment_report, finalize 等
  return 'judge'
}

/** 清理 LLM 输出中的 Markdown 格式标记，保留纯文本 */
function cleanMarkdown(text: string): string {
  return text
    // 移除代码块
    .replace(/```[\s\S]*?```/g, '')
    // 移除行内代码
    .replace(/`([^`]+)`/g, '$1')
    // 移除粗体/斜体标记
    .replace(/\*\*\*(.+?)\*\*\*/g, '$1')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/___(.+?)___/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/_(.+?)_/g, '$1')
    // 移除标题标记
    .replace(/^#{1,6}\s+/gm, '')
    // 移除水平线
    .replace(/^---+$/gm, '')
    // 移除链接，保留文本
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // 移除 HTML 标签
    .replace(/<[^>]+>/g, '')
    // 合并多余空行
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** 判断节点是否为应该显示在聊天中的辩论发言节点 */
function isDebateSpeechNode(node: string): boolean {
  if (!node) return false
  // 支持 subnode 格式（如 judge_opening_0, judge_opening_1）
  const baseNode = node.replace(/_\d+$/, '')
  const speechNodes = [
    'judge_opening', 'plaintiff_opening', 'defendant_opening',
    'court_investigation', 'plaintiff_rebuttal', 'defendant_rebuttal',
    'judge_comment', 'judge_verdict', 'judgment_report', 'plain_language',
  ]
  return speechNodes.includes(baseNode)
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

/** 补证面板：证据不足时供用户补充证据 */
function EvidenceSupplementPanel({ interruptReason, onSubmit }: {
  interruptReason: string
  onSubmit: (newEvidence: string) => void
}) {
  const [newEvidence, setNewEvidence] = useState('')

  return (
    <div className="border-t border-amber-500/30 bg-amber-900/20 flex-shrink-0">
      {/* 中断原因提示 */}
      <div className="px-4 pt-3 pb-2 flex items-start gap-2">
        <AlertTriangle size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
        <div>
          <p className="text-xs font-medium text-amber-300">证据不足，需要补充</p>
          <p className="text-[11px] text-amber-400/80 mt-0.5">{interruptReason}</p>
        </div>
      </div>
      {/* 补证输入区 */}
      <div className="px-4 pb-3 flex gap-2">
        <textarea
          value={newEvidence}
          onChange={e => setNewEvidence(e.target.value)}
          placeholder="请补充案件相关证据材料，如合同条款、转账记录、聊天截图描述等..."
          rows={3}
          className="input-field resize-none flex-1 !border-amber-500/30 focus:!border-amber-400/50"
        />
        <div className="flex flex-col justify-end gap-2">
          <button
            onClick={() => { if (newEvidence.trim()) { onSubmit(newEvidence.trim()); setNewEvidence('') } }}
            disabled={!newEvidence.trim()}
            className="gold-btn-sm flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >
            <Play size={12} /> 继续推演
          </button>
        </div>
      </div>
    </div>
  )
}

export default function CourtPage() {
  const { authed } = useChatStore()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [phase, setPhase] = useState<'input' | 'debating' | 'done' | 'evidence_needed'>('input')

  // 案件输入
  const [caseTitle, setCaseTitle] = useState('')
  const [caseDescription, setCaseDescription] = useState('')
  const [evidenceSummary, setEvidenceSummary] = useState('')

  // 补证状态：证据不足时保存中断原因
  const [interruptReason, setInterruptReason] = useState('')

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

  useEffect(() => {
    setSavedCases(loadCourtCases())
    // 从案件记忆页面"继续"时，恢复上次保存的案件
    const continueCaseId = localStorage.getItem('legalmind_continue_case')
    if (continueCaseId) {
      localStorage.removeItem('legalmind_continue_case')
      const cases = loadCourtCases()
      const found = cases.find(c => c.id === continueCaseId)
      if (found) {
        caseIdRef.current = found.id
        loadSavedCase(found)
      }
    }
  }, [])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const updateFlowStep = useCallback((nodeId: string, status: FlowStatus) => {
    // 支持 subnode 格式（如 judge_opening_0 → judge_opening）
    const baseNodeId = nodeId.replace(/_\d+$/, '')
    const stepId = NODE_TO_STEP[baseNodeId] || NODE_TO_STEP[nodeId]
    if (!stepId) return
    setFlowSteps(prev => prev.map(step =>
      step.id === stepId ? { ...step, status, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) } : step
    ))
  }, [])

  // 稳定 ID：开始辩论时生成，完成后保存到同一个 ID
  const caseIdRef = useRef('')

  const saveCurrentCase = useCallback((isDone: boolean = false) => {
    if (!caseDescription.trim()) return
    const id = caseIdRef.current || Date.now().toString()
    if (!caseIdRef.current) caseIdRef.current = id
    const c: SavedCourtCase = {
      id,
      title: caseTitle || '未命名案件',
      description: caseDescription,
      evidenceSummary,
      result: isDone ? {
        messages: messages.map(m => ({ ...m, timestamp: m.timestamp.toISOString() })),
        verdict: '',
        judgmentReport: '',
        plainLanguage: '',
        convergenceReason: '',
        kfe: {},
        structuredSummary: structuredReport,
      } : null,
      createdAt: savedCases.find(sc => sc.id === id)?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    // 更新或插入：同 ID 覆盖旧记录
    const existing = savedCases.filter(sc => sc.id !== id)
    const updated = [c, ...existing]
    setSavedCases(updated)
    saveCourtCases(updated)
  }, [caseTitle, caseDescription, evidenceSummary, messages, structuredReport, savedCases])

  // 用 ref 保持最新 saveCurrentCase，避免 setTimeout 闭包捕获旧版本
  const saveCurrentCaseRef = useRef(saveCurrentCase)
  saveCurrentCaseRef.current = saveCurrentCase

  const loadSavedCase = (c: SavedCourtCase) => {
    caseIdRef.current = c.id
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

  const handleStartDebate = async (keepMessages = false, overrideEvidence?: string) => {
    if (!caseDescription.trim()) return
    if (!authed) { setError('请先登录'); return }

    // 补证恢复时保留已有消息，否则清空
    if (!keepMessages) setMessages([])
    setError(null)
    setPhase('debating')
    setIsStreaming(true)
    setFlowSteps(INITIAL_FLOW_STEPS.map(s => ({ ...s, status: 'pending' as FlowStatus, time: undefined })))
    setCurrentRound(0)
    setCurrentPhaseLabel('')
    setConfidence(0)
    if (!keepMessages) {
      setEvidences([])
      setLawArticles([])
      setKfeItems([])
      setStructuredReport(null)
      setCanSign('待评估')
    }

    // 补证恢复时沿用已有 caseId，否则生成新的
    if (!keepMessages) {
      caseIdRef.current = Date.now().toString()
    }
    saveCurrentCase(false)

    const abortController = new AbortController()
    abortRef.current = abortController

    let currentRole: DebateMessage['role'] = 'judge'
    let currentContent = ''
    let currentNode = ''
    let currentRoundNum = 0

    try {
      for await (const event of debateStream({
        case_description: caseDescription,
        evidence_summary: overrideEvidence ?? evidenceSummary,
        task_type: 'debate',
      }, abortController.signal)) {

        if (event.type === 'chunk') {
          const chunk = event.data as DebateStreamChunk

          // 更新流程步骤状态（所有节点都更新）
          updateFlowStep(currentNode || chunk.node, 'done')
          updateFlowStep(chunk.node, 'running')

          if (chunk.node !== currentNode) {
            // 保存上一个节点的消息（仅辩论发言节点）
            if (currentContent && currentNode && isDebateSpeechNode(currentNode)) {
              setMessages(prev => [...prev, {
                id: `${Date.now()}-${Math.random()}`, role: currentRole,
                content: cleanMarkdown(currentContent), node: currentNode, round: currentRoundNum, timestamp: new Date(),
              }])
            }
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

          // 仅辩论发言节点实时更新消息列表
          if (isDebateSpeechNode(currentNode)) {
            const cleanedContent = cleanMarkdown(currentContent)
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last && last.node === currentNode && last.role === currentRole) {
                updated[updated.length - 1] = { ...last, content: cleanedContent }
              } else {
                updated.push({ id: `${Date.now()}-${Math.random()}`, role: detectRole(chunk.node), content: cleanedContent, node: currentNode, round: currentRoundNum, timestamp: new Date() })
              }
              return updated
            })
          }

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
          if (currentContent && currentNode && isDebateSpeechNode(currentNode)) {
            setMessages(prev => [...prev, {
              id: `${Date.now()}-${Math.random()}`, role: currentRole,
              content: cleanMarkdown(currentContent), node: currentNode, round: currentRoundNum, timestamp: new Date(),
            }])
          }

          const done = event.data as DebateStreamDone & { legal_knowledge?: string; kfe?: Record<string, unknown> }

          // 证据不足时：更新流程步骤到 check_evidence 为止，后续保持 pending
          if (done.evidence_sufficient === false) {
            updateFlowStep('extract_kfe', 'done')
            updateFlowStep('check_evidence', 'done')
          } else {
            updateFlowStep(currentNode || 'finalize', 'done')
            setFlowSteps(prev => prev.map(s => ({ ...s, status: 'done' as FlowStatus })))
          }

          const summary = done.structured_summary

          if (summary) {
            setStructuredReport(summary)
            if (summary.kfe_items?.length) setKfeItems(summary.kfe_items)
            if (summary.law_articles?.length) setLawArticles(summary.law_articles)
            if (summary.evidence_analysis?.length) setEvidences(summary.evidence_analysis.map(e => ({ name: e.name, type: e.type, relevance: e.relevance, conclusion: e.conclusion })))
            if (summary.confidence_score) setConfidence(summary.confidence_score)
            if (summary.can_sign) setCanSign(summary.can_sign)
          }

          // 从 done 事件补充右侧面板数据（structured_summary 可能为空）
          // KFE 数据
          if (!summary?.kfe_items?.length && done.kfe) {
            const items = Object.entries(done.kfe).map(([key, val]) => ({
              label: key, value: typeof val === 'string' ? val : JSON.stringify(val), status: 'verified' as const,
            }))
            if (items.length > 0) setKfeItems(items)
          }
          // 法律知识数据
          if (!summary?.law_articles?.length && done.legal_knowledge) {
            const lines = done.legal_knowledge.split('\n').filter((l: string) => l.trim())
            const articles = lines.slice(0, 6).map((line: string) => ({
              title: line.split('：')[0]?.trim() || line.slice(0, 40),
              source: '法律库',
              excerpt: line.split('：')[1]?.trim() || line.slice(0, 80),
              relevance: '直接相关',
            }))
            if (articles.length > 0) setLawArticles(articles)
          }

          // 证据不足时进入补证阶段，否则正常完成
          if (done.evidence_sufficient === false) {
            setInterruptReason(done.interrupt_reason || '证据不足，无法继续推演')
            setPhase('evidence_needed')
          } else {
            setPhase('done')
            // 延迟保存：让 React 先提交所有状态更新，确保 messages/structuredReport 是最新值
            setTimeout(() => {
              saveCurrentCaseRef.current(true)
              // 同步到后端 Redis（已登录时）
              if (authed) {
                import('@/app/lib/api').then(({ createCase }) => {
                  createCase(caseTitle || '未命名案件', caseDescription.slice(0, 200)).catch(() => {})
                }).catch(() => {})
              }
            }, 0)
          }
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
    setCurrentRound(0); setCurrentPhaseLabel(''); setConfidence(0); setPhase('input'); setError(null); setInterruptReason('')
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
      case 'running': return <Loader2 size={14} className="text-gold-300 animate-spin" />
      case 'done': return <CircleCheck size={14} className="text-emerald-400" />
      case 'error': return <X size={14} className="text-red-400" />
      default: return <Circle size={14} className="text-slate-500" />
    }
  }

  const CAN_SIGN_STYLE: Record<string, { bg: string; text: string; border: string; label: string }> = {
    '可签': { bg: 'bg-emerald-400/10', text: 'text-emerald-300', border: 'border-emerald-400/30', label: '可签' },
    '有条件可签': { bg: 'bg-gold-400/10', text: 'text-gold-300', border: 'border-gold-400/30', label: '有条件可签' },
    '不建议签': { bg: 'bg-red-400/10', text: 'text-red-300', border: 'border-red-400/30', label: '不建议签' },
    '待评估': { bg: 'bg-slate-400/10', text: 'text-slate-400', border: 'border-slate-400/30', label: '待评估' },
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex flex-col bg-navy-950 overflow-hidden">
        {/* 顶部标题栏 */}
        <div className="h-14 border-b border-navy-700/30 flex items-center justify-between px-6 bg-navy-950 backdrop-blur-sm flex-shrink-0">
          <div className="flex items-center gap-3">
            <Gavel size={20} className="text-gold-400" />
            <h1 className="text-base font-semibold font-display text-slate-50">{caseTitle || '模拟法庭推演'}</h1>
            {phase !== 'input' && (
              <>
                <span className="text-slate-600">|</span>
                <span className="text-xs text-slate-300">
                  当前阶段：<span className="text-gold-300 font-medium">{currentPhaseLabel || '准备中'}</span>
                  {currentRound > 0 && <span className="ml-1">（第{currentRound}轮）</span>}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            {phase !== 'input' && canSign !== '待评估' && (
              <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border ${CAN_SIGN_STYLE[canSign].bg} ${CAN_SIGN_STYLE[canSign].border}`}>
                <div className={`w-2 h-2 rounded-full ${canSign === '可签' ? 'bg-emerald-400' : canSign === '不建议签' ? 'bg-red-400' : 'bg-gold-400'}`} />
                <span className={`text-xs font-medium ${CAN_SIGN_STYLE[canSign].text}`}>{CAN_SIGN_STYLE[canSign].label}</span>
                <span className="text-[10px] opacity-70 ml-1 text-slate-400">置信度 {confidence}%</span>
              </div>
            )}
            <button onClick={handleExportReport} disabled={phase === 'input'} className="gold-btn-sm flex items-center gap-1.5 disabled:opacity-30"><Download size={12} /> 导出报告</button>
          </div>
        </div>

        {/* 主内容区 */}
        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：推演流程 */}
          <aside className="w-56 border-r border-navy-700/30 flex-shrink-0 overflow-y-auto bg-navy-900/50">
            <div className="p-4">
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-navy-700/30">
                <div className="flex items-center gap-2"><Clock size={14} className="text-gold-400" /><span className="text-xs font-medium text-slate-400">推演流程</span></div>
              </div>

              {/* 历史案件 */}
              {savedCases.length > 0 && phase === 'input' && (
                <>
                  <div className="mb-3">
                    <h4 className="text-[10px] text-slate-400 mb-2">历史案件</h4>
                    <div className="space-y-1 max-h-40 overflow-y-auto">
                      {savedCases.slice(0, 5).map(c => (
                        <button key={c.id} onClick={() => loadSavedCase(c)}
                          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-navy-800/50 transition-colors group">
                          <p className="text-[11px] text-slate-300 truncate group-hover:text-slate-200">{c.title}</p>
                          <p className="text-[9px] text-slate-500">{new Date(c.createdAt).toLocaleDateString('zh-CN')}</p>
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="border-t border-navy-700/30 mb-4" />
                </>
              )}

              <div className="space-y-0.5">
                {flowSteps.map((step) => (
                  <motion.div key={step.id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                    className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-xs cursor-default transition-all ${
                      step.status === 'running' ? 'bg-gold-400/10 border border-gold-400/20' : step.status === 'done' ? 'hover:bg-navy-800/30' : 'opacity-50'
                    }`}>
                    {flowIcon(step.status)}
                    <span className={`flex-1 truncate ${step.status === 'running' ? 'text-gold-300 font-medium' : step.status === 'done' ? 'text-emerald-400' : 'text-slate-400'}`}>{step.label}</span>
                    {step.time && <span className="text-[10px] text-slate-500">{step.time}</span>}
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
                    <Gavel size={36} className="text-gold-400 mx-auto mb-3" />
                    <h2 className="text-xl font-bold font-display text-slate-50">模拟法庭推演</h2>
                    <p className="text-sm text-slate-400 mt-1 font-body">输入案件信息，启动多智能体庭审辩论</p>
                  </div>

                  <div>
                    <label className="text-xs text-slate-300 mb-1.5 block font-body">案件标题</label>
                    <input value={caseTitle} onChange={e => setCaseTitle(e.target.value)}
                      placeholder="例：民间借贷纠纷案"
                      className="input-field" />
                  </div>

                  <div>
                    <label className="text-xs text-slate-300 mb-1.5 block font-body">案件描述 <span className="text-red-400">*</span></label>
                    <textarea value={caseDescription} onChange={e => setCaseDescription(e.target.value)}
                      placeholder="请详细描述案件事实、当事人关系、争议内容..."
                      rows={6}
                      className="input-field resize-none" />
                  </div>

                  <div>
                    <label className="text-xs text-slate-300 mb-1.5 block font-body">证据摘要（可选）</label>
                    <textarea value={evidenceSummary} onChange={e => setEvidenceSummary(e.target.value)}
                      placeholder="列举案件相关证据材料..."
                      rows={3}
                      className="input-field resize-none" />
                  </div>

                  <button onClick={() => handleStartDebate()} disabled={!caseDescription.trim()}
                    className="w-full gold-btn py-3 flex items-center justify-center gap-2 text-base disabled:opacity-40">
                    <Play size={18} /> 开始庭审推演
                  </button>
                </div>
              </div>
            ) : (
              /* 辩论进行中/完成 */
              <>
                <div className="h-11 border-b border-navy-700/30 flex items-center justify-between px-4 flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-300"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/></svg>
                    <span className="text-xs font-medium text-slate-400 font-body">庭审推演（多智能体协同）</span>
                  </div>
                  <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} className="text-[10px] bg-transparent border border-navy-700/30 rounded px-2 py-1 text-slate-400 focus:outline-none focus:border-gold-400/30">
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
                        <motion.div key={msg.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className={`glass-card-static rounded-xl ${config.bg} border ${config.border} p-4`}>
                          <div className="flex items-start gap-3">
                            <div className={`w-9 h-9 rounded-full ${config.avatar} flex items-center justify-center flex-shrink-0`}><IconComp size={16} className="text-white" /></div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1.5">
                                <span className={`text-sm font-semibold ${config.text}`}>{config.label}</span>
                                {msg.round && <span className="text-[10px] px-1.5 py-0.5 rounded bg-navy-800/50 text-slate-400">第{msg.round}轮</span>}
                                <span className="text-[10px] text-slate-500 ml-auto">{msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                              </div>
                              <div className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap font-body">{msg.content}</div>
                            </div>
                          </div>
                        </motion.div>
                      )
                    })}
                  </AnimatePresence>
                  {isStreaming && messages.length === 0 && (
                    <div className="flex items-center justify-center py-20">
                      <div className="flex items-center gap-3 text-slate-400"><Loader2 size={20} className="animate-spin text-gold-400" /><span className="text-sm font-body">正在分析案情，提取关键法律事实...</span></div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* 底部操作栏：正常状态 */}
                {phase !== 'evidence_needed' && (
                  <div className="h-11 border-t border-navy-700/30 flex items-center justify-between px-4 flex-shrink-0 bg-navy-950">
                    <div className="flex items-center gap-2">
                      {isStreaming && (<button onClick={handleStop} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-400/30 text-red-400 text-xs hover:bg-red-400/10"><StopCircle size={12} /> 停止推演</button>)}
                      {phase === 'done' && !isStreaming && (<button onClick={handleReset} className="gold-btn-outline flex items-center gap-1.5 px-3 py-1.5 text-xs"><RefreshCw size={12} /> 新案件</button>)}
                    </div>
                  </div>
                )}

                {/* 补证面板：证据不足时显示 */}
                {phase === 'evidence_needed' && (
                  <EvidenceSupplementPanel
                    interruptReason={interruptReason}
                    onSubmit={(newEvidence) => {
                      // 将新证据追加到已有证据摘要中，直接传入避免异步状态问题
                      const combined = evidenceSummary
                        ? `${evidenceSummary}\n\n【补充证据】\n${newEvidence}`
                        : newEvidence
                      setEvidenceSummary(combined)
                      handleStartDebate(true, combined)
                    }}
                  />
                )}
              </>
            )}
          </section>

          {/* 右侧信息面板 */}
          <aside className="w-72 border-l border-navy-700/30 flex-shrink-0 overflow-y-auto bg-navy-900/50">
            <div className="p-4">
              <div className="flex items-center gap-1 mb-4 p-1 rounded-lg bg-navy-800/30">
                {(['evidence', 'law', 'kfe'] as const).map(tab => (
                  <button key={tab} onClick={() => setActiveRightTab(tab)} className={`flex-1 text-[11px] py-1.5 rounded-md transition-all font-medium ${activeRightTab === tab ? 'bg-gold-400/10 text-gold-300 shadow-sm' : 'text-slate-400 hover:text-slate-300'}`}>
                    {tab === 'evidence' ? '证据' : tab === 'law' ? '法条' : 'KFE'}
                  </button>
                ))}
              </div>

              {activeRightTab === 'evidence' && (
                <div className="space-y-3">
                  <span className="text-xs font-medium text-slate-400">证据分析 ({evidences.length})</span>
                  {evidences.length > 0 ? (
                    <div className="space-y-2">
                      {evidences.map((ev, i) => (
                        <div key={i} className="glass-card-static rounded-lg p-2.5">
                          <div className="flex items-start gap-2">
                            <FileText size={12} className="text-gold-400 mt-0.5" />
                            <div>
                              <p className="text-[11px] text-slate-300">{ev.name}</p>
                              <p className="text-[9px] text-slate-500">{ev.relevance} · {ev.conclusion?.slice(0, 30)}</p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-500 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '等待证据分析完成...'}</p>
                  )}
                </div>
              )}

              {activeRightTab === 'law' && (
                <div className="space-y-3">
                  <span className="text-xs font-medium text-slate-400">引用法条 ({lawArticles.length})</span>
                  {lawArticles.length > 0 ? (
                    <div className="space-y-2">
                      {lawArticles.map((a, i) => (
                        <div key={i} className="glass-card-static rounded-lg p-2.5">
                          <div className="flex items-center gap-1.5 mb-1"><BookOpen size={10} className="text-gold-400/60" /><span className="text-[10px] text-gold-300 font-medium line-clamp-1">{a.title}</span></div>
                          <p className="text-[10px] text-slate-400 leading-relaxed line-clamp-2">{a.excerpt}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-500 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '辩论中自动检索...'}</p>
                  )}
                </div>
              )}

              {activeRightTab === 'kfe' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-slate-400">KFE 关键要素</span>
                  </div>
                  {kfeItems.length > 0 ? (
                    <div className="space-y-2">
                      {kfeItems.map((item, i) => (
                        <div key={i} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-navy-800/30">
                          <span className="text-[11px] text-slate-400 w-16 flex-shrink-0">{item.label}</span>
                          <span className="text-[11px] text-slate-300 truncate">{item.value}</span>
                          <span className={`text-[10px] flex-shrink-0 ml-2 ${item.status === 'verified' ? 'text-emerald-400' : item.status === 'unverified' ? 'text-red-400' : 'text-slate-500'}`}>
                            {item.status === 'verified' ? '已收敛' : item.status === 'unverified' ? '未收敛' : '待检测'}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-500 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '正在提取关键法律事实...'}</p>
                  )}
                </div>
              )}
            </div>
          </aside>
        </div>

        {/* 底部报告区 */}
        {messages.length > 0 && (
          <div className="h-52 border-t border-navy-700/30 bg-navy-950 flex-shrink-0">
            <div className="h-full flex flex-col">
              <div className="h-10 border-b border-navy-700/30 flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2"><FileText size={14} className="text-slate-300" /><span className="text-xs font-medium text-slate-400">分析报告</span></div>
                <div className="flex items-center gap-3">
                  <button onClick={() => setActiveBottomTab('report')} className={`text-[11px] px-3 py-1 rounded transition-all ${activeBottomTab === 'report' ? 'text-gold-300 bg-gold-400/10' : 'text-slate-400 hover:text-slate-300'}`}>案件分析</button>
                  <button onClick={() => setActiveBottomTab('solution')} className={`text-[11px] px-3 py-1 rounded transition-all ${activeBottomTab === 'solution' ? 'text-gold-300 bg-gold-400/10' : 'text-slate-400 hover:text-slate-300'}`}>调解方案</button>
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
                          <h4 className="text-[11px] font-semibold text-slate-200 flex items-center gap-1.5">
                            <span className="w-4 h-4 rounded bg-gold-400/10 text-gold-300 flex items-center justify-center text-[9px]">{sec.num}</span>{sec.title}
                          </h4>
                          <ul className="space-y-1.5 pl-5">
                            {(structuredReport.report_sections?.[sec.key] || ['等待生成...']).map((item, i) => (
                              <li key={i} className="text-[10px] text-slate-300 list-disc">{item}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-4 h-full">
                      <div className="glass-card-static rounded-lg p-3">
                        <h4 className="text-[11px] font-semibold text-slate-200 mb-2">调解方案草案</h4>
                        <p className="text-[10px] text-slate-300 leading-relaxed whitespace-pre-wrap font-body">{structuredReport.mediation_suggestion?.draft || '基于庭审辩论结果，建议双方就争议焦点达成谅解...'}</p>
                      </div>
                      <div className="glass-card-static rounded-lg p-3">
                        <h4 className="text-[11px] font-semibold text-slate-200 mb-2">执行保障措施</h4>
                        <p className="text-[10px] text-slate-300 leading-relaxed whitespace-pre-wrap font-body">{structuredReport.mediation_suggestion?.enforcement || '为确保调解协议得到有效执行，建议采取以下保障措施...'}</p>
                      </div>
                    </div>
                  )
                ) : (
                  <div className="flex items-center justify-center h-full text-[11px] text-slate-500">
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
