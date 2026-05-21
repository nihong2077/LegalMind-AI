'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'
import {
  Scale, Play, FileText, AlertTriangle, CheckCircle, Loader2,
  StopCircle, Plus, Download, MoreHorizontal,
  Clock, CircleCheck, Circle, BookOpen, Hash, Shield, Zap,
  Gavel, FileCheck, Eye, RefreshCw, X
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  debateStream, type DebateRequest, type DebateStreamChunk,
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
  { id: 'extract_kfe', label: '案情解析', status: 'done', node: 'extract_kfe', time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) },
  { id: 'check_evidence', label: '证据抽取', status: 'done', node: 'check_evidence', time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) },
  { id: 'retrieve_knowledge', label: 'HyDE 查询改写', status: 'pending', node: 'retrieve_knowledge' },
  { id: 'hyde_retrieve', label: '混合检索', status: 'pending', node: 'hyde_retrieve' },
  { id: 'plaintiff_opening', label: '原告律师陈述', status: 'pending', node: 'plaintiff_opening' },
  { id: 'defendant_rebuttal', label: '被告律师抗辩', status: 'pending', node: 'defendant_rebuttal' },
  { id: 'convergence_check', label: 'KFE 收敛检测', status: 'pending', node: 'convergence_check' },
  { id: 'judge_verdict', label: '法官总结', status: 'pending', node: 'judge_verdict' },
  { id: 'mediator_node', label: '调解方案生成', status: 'pending', node: 'mediator_node' },
]

const INITIAL_MESSAGES: DebateMessage[] = [
  { id: '1', role: 'judge', content: '本庭现在开庭审理原告张某诉被告李某民间借贷纠纷一案。原告，请陈述你的诉讼请求及事实理由。', node: 'judge_opening', round: 0, timestamp: new Date() },
  { id: '2', role: 'plaintiff', content: '尊敬的审判长，原告张某诉称：2023年3月，被告李某因经营需要向原告借款50万元，双方签订了借款合同，约定借款期限6个月，年利率12%，按月付息，被告以其名下房产提供抵押担保。借款到期后，被告仅支付了前3个月利息，本金50万元及剩余利息至今未还。故请求法院判令：1. 被告偿还借款本金50万元；2. 被告支付逾期利息；3. 确认原告对抵押房产享有优先受偿权。', node: 'plaintiff_opening', round: 1, timestamp: new Date() },
  { id: '3', role: 'defendant', content: '审判长，被告李某对借款事实无异议，但需要说明：1. 被告因受市场环境影响，经营困难，暂时无力偿还；2. 被告愿意分期偿还本金，但认为年利率12%过高，请求法院适当调减；3. 被告希望与原告协商延期还款方案。', node: 'defendant_rebuttal', round: 1, timestamp: new Date() },
]

const INITIAL_EVIDENCES = [
  { name: '借款合同', type: 'contract', relevance: '核心证据', conclusion: '证明双方存在50万元借贷关系，约定年利率12%' },
  { name: '银行转账凭证', type: 'financial', relevance: '核心证据', conclusion: '证明原告已实际交付50万元借款' },
  { name: '房产抵押登记', type: 'certificate', relevance: '重要证据', conclusion: '证明被告以其房产提供抵押担保' },
  { name: '微信聊天记录', type: 'digital', relevance: '辅助证据', conclusion: '证明原告多次催款，被告承认欠款事实' },
  { name: '利息转账记录', type: 'financial', relevance: '辅助证据', conclusion: '证明被告已支付前3个月利息共15000元' },
]

const INITIAL_LAW_ARTICLES = [
  { title: '《民法典》第六百六十七条', source: '法律库', excerpt: '借款合同是借款人向贷款人借款，到期返还借款并支付利息的合同', relevance: '直接相关' },
  { title: '《民法典》第六百七十六条', source: '法律库', excerpt: '借款人未按照约定的期限返还借款的，应当按照约定或者国家有关规定支付逾期利息', relevance: '直接相关' },
  { title: '《民法典》第四百一十条', source: '法律库', excerpt: '债务人不履行到期债务或者发生当事人约定的实现抵押权的情形，抵押权人可以与抵押人协议以抵押财产折价或者以拍卖、变卖该抵押财产所得的价款优先受偿', relevance: '直接相关' },
  { title: '《民间借贷司法解释》第二十五条', source: '法律库', excerpt: '出借人请求借款人按照合同约定利率支付利息的，人民法院应予支持，但是双方约定的利率超过合同成立时一年期贷款市场报价利率四倍的除外', relevance: '直接相关' },
]

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

export default function CourtPage() {
  const { authed } = useChatStore()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [phase, setPhase] = useState<'input' | 'debating' | 'done'>('debating')
  const [caseTitle, setCaseTitle] = useState('民间借贷纠纷案')
  const [caseDescription, setCaseDescription] = useState('原告张某与被告李某系朋友关系。2023年3月，李某因经营需要向张某借款50万元，双方签订借款合同，约定借款期限6个月，年利率12%，按月付息。李某以其名下一套房产作为抵押担保。借款到期后，李某仅偿还了前3个月的利息，本金及剩余利息未予偿还。张某多次催要未果，遂诉至法院，请求判令李某偿还借款本金50万元及逾期利息，并确认对抵押房产享有优先受偿权。')
  const [evidenceSummary, setEvidenceSummary] = useState('1. 借款合同原件一份；2. 银行转账凭证（50万元）；3. 房产抵押登记证明；4. 微信聊天记录（催款截图）；5. 李某前3个月利息转账记录')
  const [messages, setMessages] = useState<DebateMessage[]>(INITIAL_MESSAGES)
  const [flowSteps, setFlowSteps] = useState<FlowStep[]>(INITIAL_FLOW_STEPS)
  const [currentRound, setCurrentRound] = useState(1)
  const [currentPhaseLabel, setCurrentPhaseLabel] = useState('被告律师 第1轮')
  const [confidence, setConfidence] = useState(35)
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /* 预填充示例数据 */
  const [evidences, setEvidences] = useState(INITIAL_EVIDENCES)
  const [lawArticles, setLawArticles] = useState(INITIAL_LAW_ARTICLES)
  const [kfeItems, setKfeItems] = useState<Array<{ label: string; value: string; status: 'verified' | 'unverified' | 'pending' }>>([])
  const [structuredReport, setStructuredReport] = useState<StructuredSummary | null>(null)
  const [canSign, setCanSign] = useState<string>('待评估')

  const [activeRightTab, setActiveRightTab] = useState<'evidence' | 'law' | 'kfe'>('evidence')
  const [activeBottomTab, setActiveBottomTab] = useState<'report' | 'solution'>('report')
  const [roleFilter, setRoleFilter] = useState('all')
  const abortRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const updateFlowStep = useCallback((nodeId: string, status: FlowStatus) => {
    setFlowSteps(prev => prev.map(step =>
      step.node === nodeId ? { ...step, status, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) } : step
    ))
  }, [])

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
    let lastNodeForFlow = ''

    try {
      for await (const event of debateStream({
        case_description: caseDescription,
        evidence_summary: evidenceSummary,
        task_type: 'debate',
      }, abortController.signal)) {

        if (event.type === 'chunk') {
          const chunk = event.data as DebateStreamChunk
          const role = detectRole(chunk.node)

          if (chunk.node !== currentNode) {
            if (currentContent && currentNode) {
              setMessages(prev => [...prev, {
                id: `${Date.now()}-${Math.random()}`, role: currentRole,
                content: currentContent, node: currentNode, round: currentRoundNum, timestamp: new Date(),
              }])
            }
            if (lastNodeForFlow !== chunk.node) {
              updateFlowStep(lastNodeForFlow || chunk.node, 'done')
              updateFlowStep(chunk.node, 'running')
              lastNodeForFlow = chunk.node
            }
            currentRole = role
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
              updated.push({ id: `${Date.now()}-${Math.random()}`, role, content: currentContent, node: currentNode, round: currentRoundNum, timestamp: new Date() })
            }
            return updated
          })

        } else if (event.type === 'metadata') {
          const meta = event.data as { type: string; kfe?: Record<string, unknown> | null; legal_knowledge?: string | null }
          if (meta.type === 'extract_kfe' && meta.kfe) {
            const items: typeof kfeItems = Object.entries(meta.kfe).map(([key, val]) => ({
              label: key, value: typeof val === 'string' ? val : JSON.stringify(val), status: 'verified' as const,
            }))
            if (items.length > 0) setKfeItems(items)
          }
          if (meta.type === 'retrieve_knowledge' && meta.legal_knowledge) {
            const lines = meta.legal_knowledge.split('\n').filter((l: string) => l.trim())
            const articles: typeof lawArticles = lines.slice(0, 6).map((line: string) => ({
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

          const done = event.data as DebateStreamDone
          const summary = done.structured_summary

          if (summary) {
            setStructuredReport(summary)
            if (summary.kfe_items?.length) setKfeItems(summary.kfe_items)
            if (summary.law_articles?.length) setLawArticles(summary.law_articles)
            if (summary.evidence_analysis?.length) setEvidences(summary.evidence_analysis.map(e => ({ name: e.name, type: e.type, relevance: e.relevance, conclusion: e.conclusion })))
            if (summary.confidence_score) setConfidence(summary.confidence_score)
            if (summary.can_sign) setCanSign(summary.can_sign)
            if (summary.case_type && !caseTitle) setCaseTitle(`${summary.case_type}模拟推演`)
          }

          setPhase('done')
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
    setMessages([]); setFlowSteps(INITIAL_FLOW_STEPS.map(s => ({ ...s, status: 'pending' as FlowStatus, time: undefined })))
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
    '可签': { bg: 'bg-green-500/10', text: 'text-green-400', label: '✅ 可签' },
    '有条件可签': { bg: 'bg-yellow-500/10', text: 'text-yellow-400', label: '⚠️ 有条件可签' },
    '不建议签': { bg: 'bg-red-500/10', text: 'text-red-400', label: '🚫 不建议签' },
    '待评估': { bg: 'bg-gray-500/10', text: 'text-gray-400', label: '⏳ 待评估' },
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
            <>
              <span className="text-gold-200/40">|</span>
              <span className="text-xs text-gold-200/60">
                当前阶段：<span className="text-blue-400 font-medium">{currentPhaseLabel || '准备中'}</span>
                {currentRound > 0 && <span className="ml-1">（第{currentRound}轮）</span>}
              </span>
            </>
          </div>
          <div className="flex items-center gap-3">
            <>
              <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border ${CAN_SIGN_STYLE[canSign].bg} ${CAN_SIGN_STYLE[canSign].text.replace('text-', 'border-')}`}>
                <div className={`w-2 h-2 rounded-full ${canSign === '可签' ? 'bg-green-400' : canSign === '不建议签' ? 'bg-red-400' : 'bg-yellow-400 animate-pulse'}`} />
                <span className="text-xs font-medium">{CAN_SIGN_STYLE[canSign].label}</span>
                <span className="text-[10px] opacity-70 ml-1">置信度 {confidence}%</span>
              </div>
              <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/15 border border-blue-400/30 text-blue-400 text-xs hover:bg-blue-500/25 transition-colors"><Plus size={12} /> 补充证据</button>
              <button onClick={handleExportReport} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gold-400/10 border border-gold-400/25 text-gold-300 text-xs hover:bg-gold-400/20 transition-colors"><Download size={12} /> 导出报告</button>
              <button className="p-1.5 rounded-lg hover:bg-white/5 text-gold-200/50 hover:text-gold-200 transition-colors"><MoreHorizontal size={16} /></button>
            </>
          </div>
        </div>

        {/* 主内容区 - 三栏布局 */}
        <div className="flex-1 flex overflow-hidden">
            {/* 左侧：推演流程 */}
            <aside className="w-56 border-r border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/50">
              <div className="p-4">
                <div className="flex items-center gap-2 mb-4 pb-3 border-b border-white/5">
                  <Clock size={14} className="text-blue-400" /><span className="text-xs font-medium text-gold-200/70">推演流程</span>
                </div>
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
                {isStreaming && (
                  <div className="mt-6 pt-4 border-t border-white/5 space-y-2">
                    <div className="flex items-center gap-2 text-xs text-gold-200/50"><Loader2 size={12} className="animate-spin text-blue-400" /> 正在生成庭审辩论内容...</div>
                    <div className="flex items-center gap-2 text-[10px] text-gold-200/30"><Clock size={10} /> 预计耗时 30-40 分钟</div>
                  </div>
                )}
              </div>
            </aside>

            {/* 中间：对话区域 */}
            <section className="flex-1 flex flex-col overflow-hidden min-w-0">
              <div className="h-11 border-b border-white/5 flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2">
                  <svg xmlns="http://www.w3.org/2000/svg" width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gold-200/60"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                  <span className="text-xs font-medium text-gold-200/70">庭审推演（多智能体协同）</span>
                </div>
                <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} className="text-[10px] bg-transparent border border-white/10 rounded px-2 py-1 text-gold-200/50 focus:outline-none focus:border-gold-400/30">
                  <option value="all" className="bg-[#0a1628] text-gold-200">显示全部</option>
                  <option value="judge" className="bg-[#0a1628] text-gold-200">仅法官</option>
                  <option value="lawyer" className="bg-[#0a1628] text-gold-200">仅律师</option>
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
                            {(msg.role === 'plaintiff' || msg.role === 'defendant') && msg.content.length > 50 && (
                              <div className="flex flex-wrap gap-1.5 mt-2.5 pt-2.5 border-t border-white/5">
                                {structuredReport?.focus_points?.slice(0, 4).map((fp, i) => (
                                  <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-blue-400/10 text-blue-400 border border-blue-400/20">{fp}</span>
                                ))}
                                {msg.role === 'defendant' && <span className="text-[10px] px-2 py-0.5 rounded-full bg-yellow-400/10 text-yellow-400 border border-yellow-400/20 flex items-center gap-0.5"><Zap size={8} /> 待履行标注</span>}
                              </div>
                            )}
                            {msg.role === 'mediator' && structuredReport?.mediation_suggestion?.draft && (
                              <div className="mt-2 pt-2 border-t border-white/5">
                                <div className="inline-flex items-center gap-1 text-[10px] text-green-400"><CheckCircle size={12} /> 建议双方围绕争议焦点达成谅解...</div>
                              </div>
                            )}
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
            </section>

            {/* 右侧：信息面板 */}
            <aside className="w-72 border-l border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/50">
              <div className="p-4">
                <div className="flex items-center gap-1 mb-4 p-1 rounded-lg bg-white/5">
                  {(['evidence', 'law', 'kfe'] as const).map(tab => (
                    <button key={tab} onClick={() => setActiveRightTab(tab)} className={`flex-1 text-[11px] py-1.5 rounded-md transition-all font-medium ${activeRightTab === tab ? 'bg-blue-500/20 text-blue-400 shadow-sm' : 'text-gold-200/45 hover:text-gold-200/70'}`}>
                      {tab === 'evidence' ? '证据' : tab === 'law' ? '法条' : '关键事实'}
                    </button>
                  ))}
                </div>

                {activeRightTab === 'evidence' && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-gold-200/70">证据分析 ({evidences.length})</span>
                      {evidences.length === 0 && isStreaming && <span className="text-[10px] text-gold-200/30">等待KFE提取完成...</span>}
                    </div>
                    {evidences.length > 0 ? (
                      <div className="grid grid-cols-1 gap-2">
                        {evidences.map((ev, i) => (
                          <div key={i} className="rounded-lg bg-white/[0.03] border border-white/5 p-2.5 hover:border-gold-400/20 transition-all group">
                            <div className="flex items-start gap-2">
                              <div className={`w-7 h-7 rounded flex items-center justify-center flex-shrink-0 ${ev.type === 'pdf' ? 'bg-red-500/15 text-red-400' : ev.type === 'image' ? 'bg-green-500/15 text-green-400' : 'bg-blue-500/15 text-blue-400'}`}><FileText size={12} /></div>
                              <div className="min-w-0 flex-1">
                                <p className="text-[11px] text-gold-200/80 font-medium truncate group-hover:text-gold-200">{ev.name}</p>
                                <p className="text-[9px] text-gold-200/30 mt-0.5">效力: {ev.relevance} · {ev.conclusion.slice(0, 20)}</p>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-8 text-[11px] text-gold-200/30">上传案件后自动提取证据</div>
                    )}
                  </div>
                )}

                {activeRightTab === 'law' && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-gold-200/70">引用法条 ({lawArticles.length})</span>
                      {lawArticles.length === 0 && isStreaming && <span className="text-[10px] text-gold-200/30">检索中...</span>}
                    </div>
                    {lawArticles.length > 0 ? (
                      <div className="space-y-2">
                        {lawArticles.map((article, i) => (
                          <div key={i} className="rounded-lg bg-blue-500/5 border border-blue-400/10 p-2.5">
                            <div className="flex items-center gap-1.5 mb-1"><BookOpen size={10} className="text-blue-400/60" /><span className="text-[10px] text-blue-400/90 font-medium line-clamp-1">{article.title}</span></div>
                            <p className="text-[10px] text-gold-200/45 leading-relaxed line-clamp-2">{article.excerpt}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-8 text-[11px] text-gold-200/30">辩论过程中自动检索相关法条</div>
                    )}
                  </div>
                )}

                {activeRightTab === 'kfe' && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-gold-200/70">KFE 关键要素检测</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-400/10 text-orange-400 border border-orange-400/20">收敛检测</span>
                    </div>
                    {kfeItems.length > 0 ? (
                      <>
                        <div className="space-y-2">
                          {kfeItems.map((item, i) => (
                            <div key={i} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-white/[0.02] transition-colors">
                              <div className="flex items-center gap-2 min-w-0"><span className="text-[11px] text-gold-200/55 w-14 flex-shrink-0">{item.label}</span><span className="text-[11px] text-gold-200/75 truncate">{item.value}</span></div>
                              <span className={`text-[10px] flex-shrink-0 ml-2 ${item.status === 'verified' ? 'text-green-400' : item.status === 'unverified' ? 'text-red-400' : 'text-gold-200/30'}`}>{item.status === 'verified' ? '● 已收敛' : item.status === 'unverified' ? '● 未收敛' : '○ 待检测'}</span>
                            </div>
                          ))}
                        </div>
                        <div className="mt-3 pt-3 border-t border-white/5">
                          <div className="flex items-center justify-between">
                            <span className="text-[11px] text-gold-200/55">整体收敛状态:</span>
                            <span className="text-[11px] px-2 py-0.5 rounded-full bg-orange-400/10 text-orange-400 border border-orange-400/20 flex items-center gap-1"><Hash size={9} /> 部分收敛 ({kfeItems.filter(k => k.status === 'verified').length}/{kfeItems.length})</span>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="text-center py-8 text-[11px] text-gold-200/30">正在提取关键法律事实...</div>
                    )}
                  </div>
                )}
              </div>
            </aside>
          </div>

        {/* 底部文书工作台 */}
        {messages.length > 0 && (
          <div className="h-52 border-t border-white/5 bg-[#0c1729]/80 flex-shrink-0">
            <div className="h-full flex flex-col">
              <div className="h-10 border-b border-white/5 flex items-center justify-between px-4 flex-shrink-0">
                <div className="flex items-center gap-2"><FileCheck size={14} className="text-gold-200/60" /><span className="text-xs font-medium text-gold-200/70">文书工作台</span></div>
                <div className="flex items-center gap-3">
                  <button onClick={() => setActiveBottomTab('report')} className={`text-[11px] px-3 py-1 rounded transition-all ${activeBottomTab === 'report' ? 'text-blue-400 bg-blue-500/15 border-b-2 border-blue-400' : 'text-gold-200/40 hover:text-gold-200/60'}`}>案件分析报告</button>
                  <button onClick={() => setActiveBottomTab('solution')} className={`text-[11px] px-3 py-1 rounded transition-all ${activeBottomTab === 'solution' ? 'text-blue-400 bg-blue-500/15 border-b-2 border-blue-400' : 'text-gold-200/40 hover:text-gold-200/60'}`}>调解方案</button>
                  <button className="flex items-center gap-1 text-[10px] text-gold-200/40 hover:text-gold-200/60"><Eye size={10} /> 查看报告 <X size={8} /></button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-4">
                {structuredReport ? (
                  activeBottomTab === 'report' ? (
                    <div className="grid grid-cols-4 gap-4 h-full">
                      {[
                        { key: 'case_analysis' as const, title: '案情分析报告', num: '一' },
                        { key: 'fact_finding' as const, title: '事实认定分析', num: '二' },
                        { key: 'legal_application' as const, title: '法律适用分析', num: '三' },
                        { key: 'conclusion' as const, title: '裁判结论建议', num: '四' },
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
                      <div className="glass-card-static p-4">
                        <h4 className="text-[11px] font-semibold text-gold-200/80 mb-2">调解方案草案</h4>
                        <p className="text-[10px] text-gold-200/60 leading-relaxed whitespace-pre-wrap">{structuredReport.mediation_suggestion?.draft || '基于庭审辩论结果，建议双方就以下条款达成一致...'}</p>
                      </div>
                      <div className="glass-card-static p-4">
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
