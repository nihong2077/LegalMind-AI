'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'
import JudgeVerdictCard from '@/components/JudgeVerdictCard'
import Disclaimer from '@/components/Disclaimer'
import {
  Scale, Play, FileText, AlertTriangle, CheckCircle, Loader2,
  StopCircle, Download,
  Clock, CircleCheck, Circle, BookOpen,
  Gavel, RefreshCw, X, Upload, Paperclip, FileType2
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  debateStream, uploadDocument, getDocumentContent,
  type DebateStreamChunk,
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
  judge:     { label: '法官', icon: Scale, color: '#3b82f6', bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-600', avatar: 'bg-blue-500' },
  plaintiff: { label: '原告律师', icon: FileText, color: '#f97316', bg: 'bg-orange-50', border: 'border-orange-200', text: 'text-orange-600', avatar: 'bg-orange-500' },
  defendant: { label: '被告律师', icon: AlertTriangle, color: '#a855f7', bg: 'bg-purple-50', border: 'border-purple-200', text: 'text-purple-600', avatar: 'bg-purple-500' },
  mediator:  { label: '调解员', icon: CheckCircle, color: '#22c55e', bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-600', avatar: 'bg-green-500' },
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
const CONTINUE_CASE_KEY = 'legalmind_continue_case'

// 按用户名隔离 localStorage key，避免不同账号数据串用
function getStorageKey(base: string): string {
  if (typeof window === 'undefined') return base
  const username = localStorage.getItem('legalmind_username')
  return username ? `${base}:${username}` : base
}

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
    const raw = localStorage.getItem(getStorageKey(COURT_CASES_KEY))
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveCourtCases(cases: SavedCourtCase[]) {
  if (typeof window === 'undefined') return
  localStorage.setItem(getStorageKey(COURT_CASES_KEY), JSON.stringify(cases.slice(0, 50)))
}

/** 补证面板：证据不足时供用户补充证据 */
function EvidenceSupplementPanel({ interruptReason, onSubmit }: {
  interruptReason: string
  onSubmit: (newEvidence: string) => void
}) {
  const [newEvidence, setNewEvidence] = useState('')

  return (
    <div className="border-t border-amber-300/40 bg-amber-50/50 flex-shrink-0">
      {/* 中断原因提示 */}
      <div className="px-4 pt-3 pb-2 flex items-start gap-2">
        <AlertTriangle size={16} className="text-amber-500 mt-0.5 flex-shrink-0" />
        <div>
          <p className="text-xs font-medium text-amber-700">证据不足，需要补充</p>
          <p className="text-[11px] text-amber-600/80 mt-0.5">{interruptReason}</p>
        </div>
      </div>
      {/* 补证输入区 */}
      <div className="px-4 pb-3 flex gap-2">
        <textarea
          value={newEvidence}
          onChange={e => setNewEvidence(e.target.value)}
          placeholder="请补充案件相关证据材料，如合同条款、转账记录、聊天截图描述等..."
          rows={3}
          className="flex-1 bg-white border border-amber-300/50 rounded-lg px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-amber-400 transition-all resize-none"
        />
        <div className="flex flex-col justify-end gap-2">
          <button
            onClick={() => { if (newEvidence.trim()) { onSubmit(newEvidence.trim()); setNewEvidence('') } }}
            disabled={!newEvidence.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-amber-500 text-white text-xs font-medium hover:bg-amber-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
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

  // 文件上传
  const [uploadedFiles, setUploadedFiles] = useState<Array<{ name: string; content: string; size: number }>>([])
  const [isUploading, setIsUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

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
    const continueCaseId = localStorage.getItem(getStorageKey(CONTINUE_CASE_KEY))
    if (continueCaseId) {
      localStorage.removeItem(getStorageKey(CONTINUE_CASE_KEY))
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

  const handleStartDebate = async (keepMessages = false, overrideEvidence?: string, evidenceSupplemented = false) => {
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
    }

    // 补证后跳过开庭阶段，直接标记这些步骤为 done
    if (evidenceSupplemented) {
      const skippedSteps = ['judge_opening', 'plaintiff_opening', 'defendant_opening', 'court_investigation']
      const now = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      setTimeout(() => {
        setFlowSteps(prev => prev.map(step =>
          skippedSteps.includes(step.id)
            ? { ...step, status: 'done' as FlowStatus, time: now }
            : step
        ))
      }, 0)
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

    // 流式渲染节流：用 rAF 保证每帧最多更新一次 DOM
    let rafId: number | null = null
    let pendingUpdate: (() => void) | null = null
    const flushUpdate = () => {
      if (pendingUpdate) {
        pendingUpdate()
        pendingUpdate = null
      }
      rafId = null
    }
    const scheduleUpdate = (update: () => void) => {
      pendingUpdate = update
      if (!rafId) {
        rafId = requestAnimationFrame(flushUpdate)
      }
    }

    try {
      for await (const event of debateStream({
        case_description: caseDescription,
        evidence_summary: overrideEvidence ?? evidenceSummary,
        task_type: 'debate',
        evidence_supplemented: evidenceSupplemented,
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

          // 仅辩论发言节点实时更新消息列表（rAF 节流）
          if (isDebateSpeechNode(currentNode)) {
            const capturedContent = cleanMarkdown(currentContent)
            const capturedNode = currentNode
            const capturedRole = currentRole
            const capturedRound = currentRoundNum
            scheduleUpdate(() => {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last && last.node === capturedNode && last.role === capturedRole) {
                  updated[updated.length - 1] = { ...last, content: capturedContent }
                } else {
                  updated.push({ id: `${Date.now()}-${Math.random()}`, role: capturedRole, content: capturedContent, node: capturedNode, round: capturedRound, timestamp: new Date() })
                }
                return updated
              })
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
            if (rafId) { cancelAnimationFrame(rafId); rafId = null; pendingUpdate = null }
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
          }

          // 从 done 事件补充右侧面板数据（structured_summary 可能为空或字段缺失）
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
          // 证据分析数据：从 KFE 中提取证据相关条目作为补充
          if (!summary?.evidence_analysis?.length && done.kfe) {
            const kfeEntries = Object.entries(done.kfe).filter(([key]) =>
              key.toLowerCase().includes('evidence') || key.toLowerCase().includes('证据') ||
              key.toLowerCase().includes('proof') || key.toLowerCase().includes('document') ||
              key.toLowerCase().includes('文件') || key.toLowerCase().includes('合同')
            )
            const evidenceItems = kfeEntries.map(([key, val]) => ({
              name: key,
              type: 'text',
              relevance: '高',
              conclusion: typeof val === 'string' ? val : JSON.stringify(val),
            }))
            // 如果没有证据相关的 KFE，从所有 KFE 中提取作为证据分析
            const fallbackItems = evidenceItems.length > 0 ? evidenceItems :
              Object.entries(done.kfe).slice(0, 5).map(([key, val]) => ({
                name: key,
                type: 'text',
                relevance: '中',
                conclusion: typeof val === 'string' ? val : JSON.stringify(val),
              }))
            if (fallbackItems.length > 0) setEvidences(fallbackItems)
          }
          // 确保 structuredReport 不为空：如果 summary 为空对象，用累积数据构建基础报告
          if (summary && !summary.report_sections) {
            const kfeText = done.kfe ? Object.entries(done.kfe).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join('；') : ''
            setStructuredReport({
              ...summary,
              report_sections: {
                case_analysis: [caseDescription.slice(0, 200) || '案件基本事实已归纳'],
                fact_finding: kfeText ? [kfeText.slice(0, 300)] : ['关键事实正在认定'],
                legal_application: done.legal_knowledge ? [done.legal_knowledge.slice(0, 200)] : ['法律适用分析中'],
                conclusion: [done.verdict?.slice(0, 100) || '等待裁决'],
              },
              kfe_items: summary.kfe_items || (done.kfe ? Object.entries(done.kfe).map(([key, val]) => ({
                label: key, value: typeof val === 'string' ? val : JSON.stringify(val), status: 'verified' as const,
              })) : []),
              law_articles: summary.law_articles || [],
              evidence_analysis: summary.evidence_analysis || [],
              confidence_score: summary.confidence_score || 75,
            })
          }

          // 证据不足时进入补证阶段，否则正常完成
          // 同时检查 evidence_sufficient 和 evidence_needed（法官自主判定证据不足）
          if (done.evidence_sufficient === false || done.evidence_needed === true) {
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
      if (rafId) cancelAnimationFrame(rafId)
      if ((e as Error).name !== 'AbortError') setError(`辩论过程出错: ${(e as Error).message}`)
    } finally {
      if (rafId) cancelAnimationFrame(rafId)
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
    setEvidences([]); setLawArticles([]); setKfeItems([]); setStructuredReport(null)
    setUploadedFiles([])
  }

  // 文件上传：调用后端接口提取文本
  const handleFileUpload = async (files: FileList | File[]) => {
    if (!files || files.length === 0) return
    setIsUploading(true)
    try {
      for (const file of Array.from(files)) {
        // 校验文件类型
        const ext = file.name.split('.').pop()?.toLowerCase()
        if (!['pdf', 'docx', 'txt', 'doc'].includes(ext || '')) {
          setError(`不支持的文件格式: ${ext}（仅支持 PDF/Word/TXT）`)
          continue
        }
        // 上传 → 提取文本
        const docInfo = await uploadDocument(file)
        const extractedText = await getDocumentContent(docInfo.id)
        if (extractedText) {
          setUploadedFiles(prev => [...prev, { name: file.name, content: extractedText, size: file.size }])
          // 自动填充：第一个文件填入案情描述，后续文件追加到证据摘要
          if (uploadedFiles.length === 0 && !caseDescription) {
            setCaseDescription(extractedText.slice(0, 5000))
          } else {
            setEvidenceSummary(prev => prev ? `${prev}\n\n【${file.name}】\n${extractedText.slice(0, 2000)}` : `【${file.name}】\n${extractedText.slice(0, 2000)}`)
          }
        }
      }
    } catch (e) {
      setError(`文件上传失败: ${(e as Error).message}`)
    } finally {
      setIsUploading(false)
    }
  }

  // 拖拽事件处理
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setDragOver(true) }
  const handleDragLeave = (e: React.DragEvent) => { e.preventDefault(); setDragOver(false) }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    if (e.dataTransfer.files?.length) handleFileUpload(e.dataTransfer.files)
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
      default: return <Circle size={14} className="text-slate-400" />
    }
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex flex-col bg-white overflow-hidden">
        {/* 顶部标题栏 — 美化版 */}
        <div className="h-14 border-b border-slate-200 flex items-center justify-between px-6 bg-gradient-to-r from-white via-blue-50/30 to-white flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-sm">
              <Gavel size={16} className="text-white" />
            </div>
            <h1 className="text-base font-semibold text-slate-800">{caseTitle || '模拟法庭推演'}</h1>
            {phase !== 'input' && (
              <>
                <span className="text-slate-300">|</span>
                <span className="text-xs text-slate-500">
                  当前阶段：<span className="text-blue-500 font-medium">{currentPhaseLabel || '准备中'}</span>
                  {currentRound > 0 && <span className="ml-1 text-slate-400">（第{currentRound}轮）</span>}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            {phase !== 'input' && confidence > 0 && (
              <div className="flex items-center gap-1.5 px-3 py-1 rounded-full border bg-blue-50 border-blue-200">
                <div className="w-2 h-2 rounded-full bg-blue-400" />
                <span className="text-xs font-medium text-blue-600">推演置信度 {confidence}%</span>
              </div>
            )}
            <button onClick={handleExportReport} disabled={phase === 'input'} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-50 border border-blue-200 text-blue-500 text-xs hover:bg-blue-100 transition-colors disabled:opacity-30"><Download size={12} /> 导出报告</button>
          </div>
        </div>

        {/* 主内容区 */}
        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：推演流程 */}
          <aside className="w-56 border-r border-gray-200 flex-shrink-0 overflow-y-auto bg-slate-50">
            <div className="p-4">
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-200">
                <div className="flex items-center gap-2"><Clock size={14} className="text-blue-400" /><span className="text-xs font-medium text-slate-500">推演流程</span></div>
              </div>

              {/* 历史案件 */}
              {savedCases.length > 0 && phase === 'input' && (
                <>
                  <div className="mb-3">
                    <h4 className="text-[10px] text-slate-500 mb-2">历史案件</h4>
                    <div className="space-y-1 max-h-40 overflow-y-auto">
                      {savedCases.slice(0, 5).map(c => (
                        <button key={c.id} onClick={() => loadSavedCase(c)}
                          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-50 transition-colors group">
                          <p className="text-[11px] text-slate-600 truncate group-hover:text-slate-600">{c.title}</p>
                          <p className="text-[9px] text-slate-300">{new Date(c.createdAt).toLocaleDateString('zh-CN')}</p>
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="border-t border-gray-200 mb-4" />
                </>
              )}

              <div className="space-y-0.5">
                {flowSteps.map((step) => (
                  <motion.div key={step.id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                    className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-xs cursor-default transition-all ${
                      step.status === 'running' ? 'bg-blue-500/10 border border-blue-400/20' : step.status === 'done' ? 'hover:bg-slate-50' : 'opacity-50'
                    }`}>
                    {flowIcon(step.status)}
                    <span className={`flex-1 truncate ${step.status === 'running' ? 'text-blue-400 font-medium' : step.status === 'done' ? 'text-slate-500' : 'text-slate-500'}`}>{step.label}</span>
                    {step.time && <span className="text-[10px] text-slate-300">{step.time}</span>}
                  </motion.div>
                ))}
              </div>
            </div>
          </aside>

          {/* 中间区域 */}
          <section className="flex-1 flex flex-col overflow-hidden min-w-0">
            {phase === 'input' ? (
              /* 案件输入表单 — 美化版 */
              <div className="flex-1 overflow-y-auto p-8 flex items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50/30 to-indigo-50/20">
                <div className="w-full max-w-2xl space-y-5">
                  {/* 标题区 */}
                  <div className="text-center mb-4">
                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-500/20 mb-3">
                      <Gavel size={28} className="text-white" />
                    </div>
                    <h2 className="text-2xl font-bold bg-gradient-to-r from-slate-800 to-slate-600 bg-clip-text text-transparent">模拟法庭推演</h2>
                    <p className="text-sm text-slate-500 mt-1.5">输入案件信息或上传文件，启动多智能体庭审辩论</p>
                  </div>

                  {/* 文件上传区 */}
                  <div
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                    className={`relative rounded-2xl border-2 border-dashed transition-all cursor-pointer p-6 text-center ${
                      dragOver ? 'border-blue-400 bg-blue-50/50 scale-[1.01]' : 'border-slate-200 bg-white/50 hover:border-blue-300 hover:bg-blue-50/30'
                    }`}>
                    <input ref={fileInputRef} type="file" multiple accept=".pdf,.docx,.doc,.txt" className="hidden"
                      onChange={e => { if (e.target.files?.length) handleFileUpload(e.target.files); e.target.value = '' }} />
                    {isUploading ? (
                      <div className="flex items-center justify-center gap-2 text-blue-500">
                        <Loader2 size={18} className="animate-spin" />
                        <span className="text-sm">正在上传并提取文本...</span>
                      </div>
                    ) : (
                      <div className="flex flex-col items-center gap-1.5">
                        <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
                          <Upload size={18} className="text-blue-500" />
                        </div>
                        <p className="text-sm text-slate-600 font-medium">点击或拖拽上传案件文件</p>
                        <p className="text-[11px] text-slate-400">支持 PDF / Word / TXT，文件自动提取文本填入下方</p>
                      </div>
                    )}
                  </div>

                  {/* 已上传文件列表 */}
                  {uploadedFiles.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {uploadedFiles.map((f, i) => (
                        <div key={i} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-50 border border-blue-200 text-xs text-blue-600">
                          <FileType2 size={12} className="flex-shrink-0" />
                          <span className="truncate max-w-[180px]">{f.name}</span>
                          <span className="text-[10px] text-blue-400">{(f.size / 1024).toFixed(0)}KB</span>
                          <button onClick={(e) => { e.stopPropagation(); setUploadedFiles(prev => prev.filter((_, idx) => idx !== i)) }}
                            className="ml-1 hover:text-red-400 transition-colors"><X size={12} /></button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 案件标题 */}
                  <div>
                    <label className="text-xs font-medium text-slate-600 mb-1.5 flex items-center gap-1.5">
                      <Paperclip size={12} className="text-slate-400" /> 案件标题
                    </label>
                    <input value={caseTitle} onChange={e => setCaseTitle(e.target.value)}
                      placeholder="例：民间借贷纠纷案"
                      className="w-full bg-white border border-slate-200 rounded-xl px-4 py-3 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all shadow-sm" />
                  </div>

                  {/* 案件描述 */}
                  <div>
                    <label className="text-xs font-medium text-slate-600 mb-1.5 flex items-center gap-1.5">
                      <FileText size={12} className="text-slate-400" /> 案件描述 <span className="text-red-400">*</span>
                    </label>
                    <textarea value={caseDescription} onChange={e => setCaseDescription(e.target.value)}
                      placeholder="请详细描述案件事实、当事人关系、争议内容..."
                      rows={6}
                      className="w-full bg-white border border-slate-200 rounded-xl px-4 py-3 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all resize-none shadow-sm" />
                  </div>

                  {/* 证据摘要 */}
                  <div>
                    <label className="text-xs font-medium text-slate-600 mb-1.5 flex items-center gap-1.5">
                      <Scale size={12} className="text-slate-400" /> 证据摘要（可选）
                    </label>
                    <textarea value={evidenceSummary} onChange={e => setEvidenceSummary(e.target.value)}
                      placeholder="列举案件相关证据材料，如合同条款、转账记录、聊天截图描述等..."
                      rows={3}
                      className="w-full bg-white border border-slate-200 rounded-xl px-4 py-3 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all resize-none shadow-sm" />
                  </div>

                  {/* 开始按钮 */}
                  <button onClick={() => handleStartDebate()} disabled={!caseDescription.trim() || isUploading}
                    className="w-full py-3.5 flex items-center justify-center gap-2 text-base font-medium text-white rounded-xl bg-gradient-to-r from-blue-500 to-indigo-600 hover:from-blue-600 hover:to-indigo-700 shadow-lg shadow-blue-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed">
                    <Play size={18} /> 开始庭审推演
                  </button>
                  <Disclaimer variant="compact" />
                </div>
              </div>
            ) : (
              /* 辩论进行中/完成 — 美化版 */
              <>
                <div className="h-11 border-b border-gray-200 flex items-center justify-between px-4 flex-shrink-0 bg-gradient-to-r from-slate-50 to-white">
                  <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center">
                      <Scale size={12} className="text-blue-500" />
                    </div>
                    <span className="text-xs font-medium text-slate-600">庭审推演</span>
                    <span className="text-[10px] text-slate-400">多智能体协同</span>
                  </div>
                  <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} className="text-[10px] bg-white border border-slate-200 rounded-lg px-2 py-1 text-slate-500 focus:outline-none focus:border-blue-300 cursor-pointer">
                    <option value="all">显示全部</option>
                    <option value="judge">仅法官</option>
                    <option value="lawyer">仅律师</option>
                  </select>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {error && (
                    <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-red-500 text-xs flex items-center gap-2">
                      <AlertTriangle size={14} className="flex-shrink-0" /> {error}
                    </div>
                  )}
                  <AnimatePresence>
                    {messages.filter(msg => {
                      if (roleFilter === 'all') return true
                      if (roleFilter === 'judge') return msg.role === 'judge'
                      if (roleFilter === 'lawyer') return msg.role === 'plaintiff' || msg.role === 'defendant'
                      return true
                    }).map((msg) => {
                      const config = ROLE_CONFIG[msg.role]; const IconComp = config.icon
                      return (
                        <motion.div key={msg.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                          className={`rounded-2xl ${config.bg} border ${config.border} p-4 shadow-sm hover:shadow-md transition-shadow`}>
                          <div className="flex items-start gap-3">
                            <div className={`w-9 h-9 rounded-xl ${config.avatar} flex items-center justify-center flex-shrink-0 shadow-sm`}>
                              <IconComp size={16} className="text-white" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-2">
                                <span className={`text-sm font-semibold ${config.text}`}>{config.label}</span>
                                {msg.round && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/60 text-slate-500">第{msg.round}轮</span>}
                                <span className="text-[10px] text-slate-400 ml-auto">{msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                              </div>
                              {msg.role === 'judge' ? (
                                <JudgeVerdictCard content={msg.content} />
                              ) : (
                                <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">{cleanMarkdown(msg.content)}</div>
                              )}
                            </div>
                          </div>
                        </motion.div>
                      )
                    })}
                  </AnimatePresence>
                  {isStreaming && messages.length === 0 && (
                    <div className="flex flex-col items-center justify-center py-20 gap-3">
                      <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center">
                        <Loader2 size={24} className="animate-spin text-blue-500" />
                      </div>
                      <span className="text-sm text-slate-500">正在分析案情，提取关键法律事实...</span>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* 底部操作栏：正常状态 */}
                {phase !== 'evidence_needed' && (
                  <div className="h-11 border-t border-gray-200 flex items-center justify-between px-4 flex-shrink-0 bg-white">
                    <div className="flex items-center gap-2">
                      {isStreaming && (<button onClick={handleStop} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-400/30 text-red-400 text-xs hover:bg-red-400/10"><StopCircle size={12} /> 停止推演</button>)}
                      {phase === 'done' && !isStreaming && (<button onClick={handleReset} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-blue-200 text-blue-500 text-xs hover:bg-blue-50"><RefreshCw size={12} /> 新案件</button>)}
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
                      // 补证后直接进入辩论，跳过开庭阶段，且不再触发中断
                      handleStartDebate(true, combined, true)
                    }}
                  />
                )}
              </>
            )}
          </section>

          {/* 右侧信息面板 */}
          <aside className="w-72 border-l border-gray-200 flex-shrink-0 overflow-y-auto bg-slate-50">
            <div className="p-4">
              <div className="flex items-center gap-1 mb-4 p-1 rounded-lg bg-slate-100">
                {(['evidence', 'law', 'kfe'] as const).map(tab => (
                  <button key={tab} onClick={() => setActiveRightTab(tab)} className={`flex-1 text-[11px] py-1.5 rounded-md transition-all font-medium ${activeRightTab === tab ? 'bg-blue-500/20 text-blue-400 shadow-sm' : 'text-slate-500 hover:text-slate-600'}`}>
                    {tab === 'evidence' ? '证据' : tab === 'law' ? '法条' : 'KFE'}
                  </button>
                ))}
              </div>

              {activeRightTab === 'evidence' && (
                <div className="space-y-3">
                  <span className="text-xs font-medium text-slate-500">证据分析 ({evidences.length})</span>
                  {evidences.length > 0 ? (
                    <div className="space-y-2">
                      {evidences.map((ev, i) => (
                        <div key={i} className="rounded-lg bg-slate-50 border border-gray-200 p-2.5">
                          <div className="flex items-start gap-2">
                            <FileText size={12} className="text-blue-400 mt-0.5" />
                            <div>
                              <p className="text-[11px] text-slate-600">{ev.name}</p>
                              <p className="text-[9px] text-slate-400">{ev.relevance} · {ev.conclusion?.slice(0, 30)}</p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-400 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '等待证据分析完成...'}</p>
                  )}
                </div>
              )}

              {activeRightTab === 'law' && (
                <div className="space-y-3">
                  <span className="text-xs font-medium text-slate-500">引用法条 ({lawArticles.length})</span>
                  {lawArticles.length > 0 ? (
                    <div className="space-y-2">
                      {lawArticles.map((a, i) => (
                        <div key={i} className="rounded-lg bg-blue-500/5 border border-blue-400/10 p-2.5">
                          <div className="flex items-center gap-1.5 mb-1"><BookOpen size={10} className="text-blue-400/60" /><span className="text-[10px] text-blue-400/90 font-medium line-clamp-1">{a.title}</span></div>
                          <p className="text-[10px] text-slate-500 leading-relaxed line-clamp-2">{a.excerpt}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-400 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '辩论中自动检索...'}</p>
                  )}
                </div>
              )}

              {activeRightTab === 'kfe' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-slate-500">KFE 关键要素</span>
                  </div>
                  {kfeItems.length > 0 ? (
                    <div className="space-y-2">
                      {kfeItems.map((item, i) => (
                        <div key={i} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-slate-50">
                          <span className="text-[11px] text-slate-500 w-16 flex-shrink-0">{item.label}</span>
                          <span className="text-[11px] text-slate-600 truncate">{item.value}</span>
                          <span className={`text-[10px] flex-shrink-0 ml-2 ${item.status === 'verified' ? 'text-green-400' : item.status === 'unverified' ? 'text-red-400' : 'text-slate-400'}`}>
                            {item.status === 'verified' ? '已收敛' : item.status === 'unverified' ? '未收敛' : '待检测'}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-400 text-center py-4">{phase === 'input' ? '输入案件后开始推演' : '正在提取关键法律事实...'}</p>
                  )}
                </div>
              )}
            </div>
          </aside>
        </div>

        {/* 底部报告区 */}
        {messages.length > 0 && (
          <div className="h-52 border-t border-gray-200 bg-white flex-shrink-0">
            <div className="h-full flex flex-col">
              <div className="h-10 border-b border-gray-200 flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2"><FileText size={14} className="text-slate-600" /><span className="text-xs font-medium text-slate-500">分析报告</span></div>
                <div className="flex items-center gap-3">
                  <button onClick={() => setActiveBottomTab('report')} className={`text-[11px] px-3 py-1 rounded transition-all ${activeBottomTab === 'report' ? 'text-blue-400 bg-blue-500/15' : 'text-slate-500 hover:text-slate-600'}`}>案件分析</button>
                  <button onClick={() => setActiveBottomTab('solution')} className={`text-[11px] px-3 py-1 rounded transition-all ${activeBottomTab === 'solution' ? 'text-blue-400 bg-blue-500/15' : 'text-slate-500 hover:text-slate-600'}`}>调解方案</button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-4">
                {structuredReport ? (
                  <div className="space-y-3">
                    {activeBottomTab === 'report' ? (
                      <div className="grid grid-cols-4 gap-4">
                        {[
                          { key: 'case_analysis' as const, title: '案情分析', num: '一' },
                          { key: 'fact_finding' as const, title: '事实认定', num: '二' },
                          { key: 'legal_application' as const, title: '法律适用', num: '三' },
                          { key: 'conclusion' as const, title: '裁判结论', num: '四' },
                        ].map(sec => (
                          <div key={sec.key} className="space-y-2">
                            <h4 className="text-[11px] font-semibold text-slate-600 flex items-center gap-1.5">
                              <span className="w-4 h-4 rounded bg-blue-500/20 text-blue-400 flex items-center justify-center text-[9px]">{sec.num}</span>{sec.title}
                            </h4>
                            <ul className="space-y-1.5 pl-5">
                              {(structuredReport.report_sections?.[sec.key] || ['等待生成...']).map((item, i) => (
                                <li key={i} className="text-[10px] text-slate-600 list-disc">{item}</li>
                              ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="grid grid-cols-2 gap-4">
                        <div className="border border-gray-200 rounded-lg p-3">
                          <h4 className="text-[11px] font-semibold text-slate-600 mb-2">调解方案草案</h4>
                          <p className="text-[10px] text-slate-600 leading-relaxed whitespace-pre-wrap">{structuredReport.mediation_suggestion?.draft || '基于庭审辩论结果，建议双方就争议焦点达成谅解...'}</p>
                        </div>
                        <div className="border border-gray-200 rounded-lg p-3">
                          <h4 className="text-[11px] font-semibold text-slate-600 mb-2">执行保障措施</h4>
                          <p className="text-[10px] text-slate-600 leading-relaxed whitespace-pre-wrap">{structuredReport.mediation_suggestion?.enforcement || '为确保调解协议得到有效执行，建议采取以下保障措施...'}</p>
                        </div>
                      </div>
                    )}
                    <Disclaimer variant="full" />
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-full text-[11px] text-slate-400">
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
