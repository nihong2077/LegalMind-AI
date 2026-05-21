'use client'

import { useState, useRef, useCallback } from 'react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'
import {
  Upload, FileText, CheckCircle, AlertCircle, Clock, Shield,
  Loader2, ChevronDown, Plus, Download, MoreHorizontal,
  Search, FileCheck, Eye, HelpCircle, MinusCircle,
  ArrowUpRight, StopCircle, AlertTriangle
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  uploadDocument, analyzeDocument, contractReviewStream, getDocumentContent,
  type DocumentItem, type StructuredReviewData, type ContractReviewMetadata, type ContractReviewDone
} from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

type FileStatus = 'uploading' | 'uploaded' | 'analyzing' | 'ready' | 'error' | 'reviewing'

interface DocFile {
  id: string; name: string; size: string; status: FileStatus
  type: string; serverId?: string; content?: string
}

const NODE_LABELS: Record<string, string> = {
  'classify': '条款提取与分类',
  'scan_risks': '风险扫描与漏洞检测',
  'generate_report': '生成审查报告',
  'finalize': '汇总输出',
}

const NODE_COLORS: Record<string, string> = {
  'classify': 'bg-blue-400/10 text-blue-400',
  'scan_risks': 'bg-red-400/10 text-red-400',
  'generate_report': 'bg-purple-400/10 text-purple-400',
  'finalize': 'bg-green-400/10 text-green-400',
}

type ClauseTreeItem = { id: string; label: string; status: 'pass' | 'warning' | 'danger' | 'info'; risk_count: number }
type ClauseDisplay = { title: string; content: string; status: string; tags?: string[]; suggestion?: string; location?: string }
type RiskItem = { level: string; title: string; description: string; location?: string; legal_basis?: string; suggestion?: string }
type RevisionItem = { level: string; title: string; description: string; original_text?: string; suggested_text?: string; location?: string }

function statusIcon(status: string, size = 14) {
  switch (status) {
    case 'pass': return <CheckCircle size={size} className="text-emerald-400" />
    case 'warning': return <AlertTriangle size={size} className="text-amber-400" />
    case 'danger': return <AlertCircle size={size} className="text-red-400" />
    default: return <MinusCircle size={size} className="text-gold-200/30" />
  }
}

function statusBadge(status: string) {
  const map: Record<string, { bg: string; text: string; label: string }> = {
    pass:     { bg: 'bg-emerald-500/10', text: 'text-emerald-400', label: '已通过' },
    warning:  { bg: 'bg-amber-500/10', text: 'text-amber-400', label: '需注意' },
    danger:   { bg: 'bg-red-500/10',   text: 'text-red-400',   label: '高风险' },
    info:     { bg: 'bg-slate-500/10',  text: 'text-slate-400',  label: '待审查' },
  }
  const s = map[status] || map.info
  return <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.bg} ${s.text}`}>{s.label}</span>
}

function riskBadge(level: string) {
  if (level.includes('P0') || level.includes('高')) return <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-400/25 font-medium">高风险</span>
  if (level.includes('P1') || level.includes('中')) return <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-400/25 font-medium">中风险</span>
  return <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-400/25">低风险</span>
}

/* 示例合同数据 - 民间借贷合同 */
const DEMO_CLAUSE_TREE: ClauseTreeItem[] = [
  { id: 'basic', label: '基本信息', status: 'pass', risk_count: 0 },
  { id: 'loan', label: '借款条款', status: 'pass', risk_count: 0 },
  { id: 'interest', label: '利息条款', status: 'warning', risk_count: 1 },
  { id: 'mortgage', label: '抵押担保', status: 'pass', risk_count: 0 },
  { id: 'breach', label: '违约责任', status: 'danger', risk_count: 2 },
  { id: 'dispute', label: '争议解决', status: 'pass', risk_count: 0 },
]

const DEMO_CLAUSES: ClauseDisplay[] = [
  { title: '第一条 借款金额', content: '甲方（出借人）同意向乙方（借款人）提供借款人民币伍拾万元整（¥500,000.00）。', status: 'pass', tags: ['金额明确'], location: '第一条' },
  { title: '第二条 借款期限', content: '借款期限为6个月，自2023年3月1日起至2023年9月1日止。', status: 'pass', tags: ['期限明确'], location: '第二条' },
  { title: '第三条 利率', content: '借款年利率为12%，按月付息，每月利息为人民币5000元。', status: 'warning', tags: ['利率偏高', '接近上限'], suggestion: '建议核实利率是否超过LPR四倍，当前LPR四倍约13.8%，12%在合法范围内但接近上限', location: '第三条' },
  { title: '第四条 抵押担保', content: '乙方以其名下位于XX市XX区XX路XX号房产（不动产权证号：XXX）为本合同项下借款提供抵押担保。', status: 'pass', tags: ['抵押登记'], location: '第四条' },
  { title: '第五条 违约责任', content: '若乙方未按期还款，甲方有权要求乙方支付逾期利息，逾期利息按借款利率的200%计算。若逾期超过30日，甲方有权宣布借款提前到期。', status: 'danger', tags: ['违约金过高', '加速到期条款'], suggestion: '逾期利息按200%计算可能被认定为过高，建议调整为150%以内', location: '第五条 5.1' },
  { title: '第六条 争议解决', content: '因本合同引起的争议，双方协商解决；协商不成的，向甲方所在地人民法院提起诉讼。', status: 'pass', tags: ['管辖约定'], location: '第六条' },
]

const DEMO_RISKS: RiskItem[] = [
  { level: '高风险/P0', title: '逾期利息过高', description: '逾期利息按借款利率200%计算，年化达24%，可能超过法律保护上限', location: '第五条 5.1', legal_basis: '《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》第二十五条', suggestion: '建议将逾期利息调整为借款利率的150%以内' },
  { level: '中风险/P1', title: '借款利率接近上限', description: '年利率12%接近LPR四倍（约13.8%），存在被调减风险', location: '第三条', legal_basis: '《民法典》第六百八十条', suggestion: '建议将利率调整为LPR的三倍以内，或约定浮动利率' },
  { level: '低风险/P2', title: '加速到期条款缺乏缓冲期', description: '逾期30日即宣布提前到期，期限较短', location: '第五条 5.2', legal_basis: '《民法典》第五百六十三条', suggestion: '建议将加速到期条件改为逾期60日或90日' },
]

const DEMO_REVISIONS: RevisionItem[] = [
  { level: '中风险/P1', title: '调整逾期利率', description: '将逾期利息从200%调整为150%', original_text: '逾期利息按借款利率的200%计算', suggested_text: '逾期利息按借款利率的150%计算', location: '第五条 5.1' },
  { level: '低风险/P2', title: '延长加速到期宽限期', description: '将加速到期条件从30日改为60日', original_text: '若逾期超过30日，甲方有权宣布借款提前到期', suggested_text: '若逾期超过60日，甲方有权宣布借款提前到期', location: '第五条 5.2' },
]

const DEMO_CONCLUSION = {
  overall_assessment: '本民间借贷合同整体结构完整，主要条款齐备，但违约责任条款存在高风险，逾期利息约定过高可能不被法院支持。建议在签署前修改违约条款。',
  key_findings: ['逾期利息约定为借款利率200%，年化24%，可能超过法律保护上限', '借款利率12%接近LPR四倍上限', '加速到期条款宽限期偏短'],
  must_fix_before_sign: ['降低逾期利息比例至150%以内'],
  negotiation_priority: ['协商降低借款利率', '延长加速到期宽限期'],
}

const DEMO_STATS = { total_clauses: 6, high_risk: 1, medium_risk: 1, low_risk: 1, passed: 3, completion_rate: 50 }

const DEMO_REPORT_SECTIONS: Record<string, string[]> = {
  summary: ['合同类型：民间借贷合同', '出借人：甲方（张某）', '借款人：乙方（李某）', '借款金额：50万元', '借款期限：6个月', '年利率：12%'],
  clause_details: ['第一条 借款金额 - 已通过', '第二条 借款期限 - 已通过', '第三条 利率 - 需注意', '第四条 抵押担保 - 已通过', '第五条 违约责任 - 高风险', '第六条 争议解决 - 已通过'],
  risk_summary: ['高风险：逾期利息过高（年化24%）', '中风险：借款利率接近LPR四倍上限', '低风险：加速到期宽限期偏短'],
  revision_summary: ['建议将逾期利率从200%调整为150%', '建议将加速到期条件从30日改为60日'],
  conclusion: ['整体评估：合同结构完整但违约条款需修改', '签署前必须修复：降低逾期利息比例', '谈判优先级：协商降低利率、延长宽限期'],
}

export default function DocumentUpload() {
  const { authed } = useChatStore()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [files, setFiles] = useState<DocFile[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isReviewing, setIsReviewing] = useState(false)
  const [reviewDone, setReviewDone] = useState(false)

  /* 预填充示例数据 */
  const [caseName, setCaseName] = useState('民间借贷合同审查')
  const [riskLevelLabel, setRiskLevelLabel] = useState('中高')
  const [canSign, setCanSign] = useState<string>('有条件可签')
  const [clauseTree, setClauseTree] = useState<ClauseTreeItem[]>(DEMO_CLAUSE_TREE)
  const [clausesDisplay, setClausesDisplay] = useState<ClauseDisplay[]>(DEMO_CLAUSES)
  const [riskList, setRiskList] = useState<RiskItem[]>(DEMO_RISKS)
  const [revisionList, setRevisionList] = useState<RevisionItem[]>(DEMO_REVISIONS)
  const [conclusion, setConclusion] = useState<StructuredReviewData['conclusion']>(DEMO_CONCLUSION)
  const [reportSections, setReportSections] = useState<StructuredReviewData['report_sections']>(DEMO_REPORT_SECTIONS)
  const [stats, setStats] = useState(DEMO_STATS)
  const [reviewMessages, setReviewMessages] = useState<{ node: string; content: string }[]>([])
  const [currentNode, setCurrentNode] = useState('')

  const [activeRightTab, setActiveRightTab] = useState<'risks' | 'revisions' | 'conclusion'>('risks')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [showHighOnly, setShowHighOnly] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFiles = useCallback(async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    if (!authed) { setError('请先登录'); return }
    setError(null)
    for (const f of Array.from(fileList)) {
      const ext = f.name.split('.').pop()?.toUpperCase() || 'FILE'
      const localId = Date.now().toString() + Math.random().toString(36).slice(2)
      const docFile: DocFile = { id: localId, name: f.name, size: (f.size / 1024).toFixed(1) + ' KB', status: 'uploading', type: ext }
      setFiles(prev => [...prev, docFile])
      try {
        const result = await uploadDocument(f)
        setFiles(prev => prev.map(item => item.id === localId ? { ...item, status: 'uploaded', serverId: result.id } : item))
      } catch (e) {
        setError(e instanceof Error ? e.message : '上传失败')
        setFiles(prev => prev.map(item => item.id === localId ? { ...item, status: 'error' } : item))
      }
    }
  }, [authed])

  const handleAnalyze = async (doc: DocFile) => {
    if (!doc.serverId) return
    setFiles(prev => prev.map(item => item.id === doc.id ? { ...item, status: 'analyzing' } : item))
    try {
      await analyzeDocument(doc.serverId)
      setFiles(prev => prev.map(item => item.id === doc.id ? { ...item, status: 'ready' } : item))
    } catch (e) {
      setError(e instanceof Error ? e.message : '分析失败')
      setFiles(prev => prev.map(item => item.id === doc.id ? { ...item, status: 'error' } : item))
    }
  }

  const handleContractReview = async (doc: DocFile) => {
    let contractText = doc.content || ''
    if (!contractText && doc.serverId) {
      contractText = await getDocumentContent(doc.serverId)
    }
    if (!contractText) contractText = `合同文件：${doc.name}`
    if (!contractText.trim()) return

    setIsReviewing(true); setReviewDone(false); setError(null)
    setReviewMessages([]); setCurrentNode('')
    setClauseTree([]); setClausesDisplay([]); setRiskList([]); setRevisionList([])
    setConclusion({}); setReportSections({}); setStats({ total_clauses: 0, high_risk: 0, medium_risk: 0, low_risk: 0, passed: 0, completion_rate: 0 })
    setCaseName(doc.name.replace(/\.[^.]+$/, '') + ' 审查'); setRiskLevelLabel('--')

    setFiles(prev => prev.map(item => item.id === doc.id ? { ...item, status: 'reviewing' } : item))

    const abortController = new AbortController(); abortRef.current = abortController

    try {
      for await (const event of contractReviewStream({ contract_text: contractText, user_position: '乙方', review_stance: '常规' }, abortController.signal)) {
        if (event.type === 'chunk') {
          const chunk = event.data as { node: string; content: string }
          setCurrentNode(chunk.node)
          setReviewMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.node === chunk.node) updated[updated.length - 1] = { ...last, content: last.content + chunk.content }
            else updated.push({ node: chunk.node, content: chunk.content })
            return updated
          })
        } else if (event.type === 'metadata') {
          const meta = event.data as ContractReviewMetadata
          if (meta.type === 'classify' && meta.clauses?.length) {
            const display: ClauseDisplay[] = meta.clauses.slice(0, 12).map(c => ({
              title: c.title, content: c.content.slice(0, 300), status: 'info', tags: [], location: c.title,
            }))
            setClausesDisplay(display)
            if (meta.contract_type) setCaseName(meta.contract_type + ' 合同审查')
          }
          if (meta.type === 'risks') {
            const risks: RiskItem[] = []
            const pick = (r: Record<string, unknown>, key: string, fallback = '') => String(r[key] || fallback)
            ;(meta.meso_issues || []).forEach((r: Record<string, unknown>) =>
              risks.push({ level: pick(r, 'risk_level', 'P1'), title: pick(r, 'risk_name'), description: pick(r, 'risk_consequence'), location: pick(r, 'related_clauses'), legal_basis: pick(r, 'legal_basis'), suggestion: pick(r, 'fix_suggestion') })
            )
            ;(meta.micro_issues || []).forEach((r: Record<string, unknown>) =>
              risks.push({ level: pick(r, 'risk_level', 'P2'), title: pick(r, 'risk_name'), description: pick(r, 'risk_consequence'), suggestion: pick(r, 'fix_suggestion') })
            )
            ;(meta.loopholes || []).forEach((l: Record<string, unknown>) =>
              risks.push({ level: 'P0', title: pick(l, 'type', '漏洞'), description: pick(l, 'description'), suggestion: pick(l, 'fix_suggestion') })
            )
            if (risks.length > 0) setRiskList(risks)
          }
        } else if (event.type === 'done') {
          const done = event.data as ContractReviewDone
          const sr = done.structured_review
          if (sr) {
            if (sr.clause_tree?.length) setClauseTree(sr.clause_tree)
            if (sr.clauses_display?.length) setClausesDisplay(sr.clauses_display)
            if (sr.risk_list?.length) setRiskList(sr.risk_list)
            if (sr.revision_list?.length) setRevisionList(sr.revision_list)
            if (sr.conclusion) setConclusion(sr.conclusion)
            if (sr.report_sections) setReportSections(sr.report_sections)
            if (sr.stats) setStats(sr.stats)
            if (sr.case_name) setCaseName(sr.case_name)
            if (sr.risk_level_label) setRiskLevelLabel(sr.risk_level_label)
            if (sr.can_sign) setCanSign(sr.can_sign)
          }
          setReviewDone(true)
        } else if (event.type === 'error') {
          setError((event.data as { message?: string }).message || '合同审查失败'); setReviewDone(true)
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError(`合同审查出错: ${(e as Error).message}`)
    } finally { setIsReviewing(false); abortRef.current = null; setFiles(prev => prev.map(f => f.status === 'reviewing' ? { ...f, status: 'ready' } : f)) }
  }

  const handleStop = () => { if (abortRef.current) { abortRef.current.abort(); setIsReviewing(false); setReviewDone(true) } }

  const handleExportReport = () => {
    const content = conclusion?.overall_assessment
      || (reportSections && Object.keys(reportSections).length > 0
        ? Object.entries(reportSections).map(([key, items]) => `${key}:\n${(items as string[]).join('\n')}`).join('\n\n')
        : riskList.map(r => `[${r.level}] ${r.title}: ${r.description}`).join('\n'))
      || '暂无报告内容'
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `审查报告_${new Date().toISOString().slice(0,10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleDrag = (e: React.DragEvent) => { e.preventDefault(); e.stopPropagation(); setDragActive(e.type === 'dragenter' || e.type === 'dragover') }

  const RISK_COLOR: Record<string, string> = { 高: 'text-red-400', 中: 'text-amber-400', 低: 'text-blue-400', '--': 'text-gold-200/40' }
  const CAN_SIGN_STYLE: Record<string, { bg: string; text: string; label: string }> = {
    '可签': { bg: 'bg-emerald-500/10', text: 'text-emerald-400', label: '可签' },
    '有条件可签': { bg: 'bg-amber-500/10', text: 'text-amber-400', label: '有条件可签' },
    '不建议签': { bg: 'bg-red-500/10', text: 'text-red-400', label: '不建议签' },
    '待评估': { bg: 'bg-slate-500/10', text: 'text-slate-400', label: '待评估' },
  }

  const filteredClauses = clausesDisplay.filter(c => !searchKeyword || c.title.includes(searchKeyword) || c.content.includes(searchKeyword))

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex flex-col bg-[#0a1628] overflow-hidden">
        {/* 顶部标题栏 */}
        <header className="h-14 border-b border-white/5 flex items-center justify-between px-6 bg-[#0d1a2d]/80 backdrop-blur-sm flex-shrink-0 z-10">
          <div className="flex items-center gap-3">
            <Shield size={20} className="text-blue-400" />
            <h1 className="text-base font-semibold text-gold-200">合同审查工作台</h1>
            <>
              <span className="text-sm text-gold-200/70 font-medium">{caseName}</span>
              <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                riskLevelLabel.includes('高') ? 'bg-red-500/15 text-red-400 border border-red-400/25' :
                riskLevelLabel.includes('中高') ? 'bg-orange-500/15 text-orange-400 border border-orange-400/25' :
                riskLevelLabel.includes('中') ? 'bg-amber-500/15 text-amber-400 border border-amber-400/25' :
                'bg-emerald-500/15 text-emerald-400 border border-emerald-400/25'
              }`}>综合风险：{riskLevelLabel}</span>
              <span className="text-[11px] text-gold-200/35">|</span>
              <span className="text-[11px] text-gold-200/40">审查版本：v1.0</span>
            </>
          </div>
          <div className="flex items-center gap-3">
            <>
              <button onClick={() => fileInputRef.current?.click()} className="gold-btn-sm flex items-center gap-1.5"><Plus size={12} /> 上传合同</button>
              <button onClick={handleExportReport} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/10 text-gold-300 text-xs hover:bg-white/[0.08] transition-colors"><Download size={12} /> 导出审查报告</button>
              <button className="p-1.5 rounded-lg hover:bg-white/5 text-gold-200/50"><MoreHorizontal size={16} /></button>
            </>
          </div>
        </header>

        {/* 主内容区 - 始终显示三栏布局 */}
        <div className="flex-1 flex flex-col overflow-hidden">
            {/* 三栏主体 */}
            <div className="flex-1 flex overflow-hidden min-h-0">

              {/* 左侧 - 合同结构树 */}
              <aside className="w-52 border-r border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/40">
                <div className="p-4 space-y-1">
                  <div className="flex items-center justify-between mb-3 pb-2 border-b border-white/5">
                    <span className="text-xs font-semibold text-gold-200/80">合同结构</span>
                    <span className="text-[10px] text-emerald-400">{stats.completion_rate}%</span>
                  </div>

                  {clauseTree.length > 0 ? clauseTree.map(item => (
                    <button key={item.id} className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left hover:bg-white/5 transition-colors group">
                      {statusIcon(item.status)}
                      <span className={`text-xs flex-1 truncate ${item.status === 'danger' ? 'text-red-300' : item.status === 'warning' ? 'text-amber-300' : 'text-gold-200/60 group-hover:text-gold-200/90'}`}>
                        {item.label}
                      </span>
                      {item.risk_count > 0 && (
                        <span className={`text-[10px] w-4 h-4 rounded-full flex items-center justify-center ${item.status === 'danger' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}`}>
                          {item.risk_count}
                        </span>
                      )}
                    </button>
                  )) : (
                    isReviewing ? (
                      <div className="space-y-2">
                        {[1,2,3,4,5,6].map(i => (
                          <div key={i} className="flex items-center gap-2.5 px-2.5 py-2 animate-pulse">
                            <div className="w-3.5 h-3.5 rounded-full bg-white/5" /><div className="h-2.5 flex-1 rounded bg-white/5" />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[11px] text-gold-200/30 text-center py-8">等待条款提取...</p>
                    )
                  )}
                </div>

                {/* 审查概览统计（左侧底部） */}
                {stats.total_clauses > 0 && (
                  <div className="mx-4 mb-4 mt-2 pt-3 border-t border-white/5 space-y-2">
                    <h4 className="text-[11px] font-semibold text-gold-200/70">审查概览</h4>
                    <div className="grid grid-cols-2 gap-1.5 text-[10px]">
                      <div className="flex justify-between"><span className="text-gold-200/45">共识别</span><span className="text-gold-200/80">{stats.total_clauses} 个条款</span></div>
                      <div className="flex justify-between"><span className="text-gold-200/45">发现</span><span className="text-red-400">{stats.high_risk + stats.medium_risk + stats.low_risk} 处风险</span></div>
                      <div className="flex justify-between"><span className="text-red-400">● 高风险</span><span>{stats.high_risk} 处</span></div>
                      <div className="flex justify-between"><span className="text-amber-400">● 中风险</span><span>{stats.medium_risk} 处</span></div>
                      <div className="flex justify-between"><span className="text-blue-400">● 低风险建议</span><span>{stats.low_risk} 处</span></div>
                      <div className="flex justify-between"><span className="text-emerald-400">● 已通过</span><span>{stats.passed} 处</span></div>
                    </div>
                    <div className="pt-2">
                      <div className="flex justify-between text-[10px] mb-1"><span className="text-gold-200/45">审查完成度</span><span className="text-gold-200/70">{stats.completion_rate}%</span></div>
                      <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                        <motion.div initial={{ width: 0 }} animate={{ width: `${stats.completion_rate}%` }} transition={{ duration: 0.8 }}
                          className={`h-full rounded-full ${stats.completion_rate >= 80 ? 'bg-emerald-500' : stats.completion_rate >= 50 ? 'bg-amber-500' : 'bg-red-500'}`} />
                      </div>
                    </div>
                  </div>
                )}
              </aside>

              {/* 中间 - 合同内容展示区 */}
              <section className="flex-1 flex flex-col min-w-0 overflow-hidden">
                <div className="h-10 border-b border-white/5 flex items-center justify-between px-4 flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <FileText size={13} className="text-gold-200/50" />
                    <span className="text-xs font-medium text-gold-200/70">合同内容（节选）</span>
                    {clausesDisplay.length > 0 && <span className="text-[10px] text-emerald-400">{clausesDisplay.length}00%</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="relative">
                      <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gold-200/30" />
                      <input value={searchKeyword} onChange={e => setSearchKeyword(e.target.value)}
                             placeholder="搜索条款内容" className="text-[10px] pl-7 pr-3 py-1 rounded-md bg-white/5 border border-white/8 text-gold-200/70 placeholder:text-gold-200/25 focus:outline-none focus:border-gold-400/25 w-36" />
                    </div>
                    <label className="flex items-center gap-1 text-[10px] text-gold-200/45 cursor-pointer select-none">
                      <input type="checkbox" checked={showHighOnly} onChange={e => setShowHighOnly(e.target.checked)} className="rounded border-white/20" /> 仅高危
                    </label>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {error && <div className="p-3 rounded-lg bg-red-400/10 border border-red-400/20 text-red-400 text-xs">{error}</div>}

                  {filteredClauses.length > 0 ? filteredClauses.filter(c => !showHighOnly || c.status === 'danger').map((clause, i) => (
                    <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                      className={`rounded-xl border p-4 ${
                        clause.status === 'danger' ? 'bg-red-500/[0.04] border-red-400/15' :
                        clause.status === 'warning' ? 'bg-amber-500/[0.04] border-amber-400/15' :
                        clause.status === 'pass' ? 'bg-emerald-500/[0.03] border-emerald-400/10' :
                        'bg-white/[0.02] border-white/5'
                      }`}>
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <h3 className={`text-xs font-semibold ${clause.status === 'danger' ? 'text-red-300' : clause.status === 'warning' ? 'text-amber-300' : 'text-gold-200/80'}`}>
                          {clause.title}
                        </h3>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          {statusBadge(clause.status)}
                          {clause.location && <span className="text-[9px] text-gold-200/25">位置：{clause.location}</span>}
                        </div>
                      </div>
                      <p className="text-[11px] text-gold-200/55 leading-relaxed whitespace-pre-wrap mb-2.5">{clause.content}</p>
                      {clause.tags && clause.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {clause.tags.map((tag, ti) => (
                            <span key={ti} className="text-[10px] px-2 py-0.5 rounded-full bg-red-400/8 text-red-300 border border-red-400/15">{tag}</span>
                          ))}
                        </div>
                      )}
                      {clause.suggestion && (
                        <div className="flex items-start gap-1.5 text-[10px] text-amber-350/80 bg-amber-400/[0.04] rounded-md px-2.5 py-1.5">
                          <ArrowUpRight size={11} className="mt-0.5 flex-shrink-0" />
                          <span>建议修改：{clause.suggestion}</span>
                        </div>
                      )}
                    </motion.div>
                  )) : isReviewing ? (
                    <div className="flex items-center justify-center py-20 gap-3 text-gold-200/35">
                      <Loader2 size={18} className="animate-spin text-blue-400" />
                      <span className="text-sm">正在提取条款并扫描风险...</span>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center py-20 text-gold-200/30 text-sm">暂无条款数据</div>
                  )}
                </div>
              </section>

              {/* 右侧 - 三标签面板 */}
              <aside className="w-80 border-l border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/40">
                <div className="sticky top-0 z-10 bg-[#0c1729]/95 backdrop-blur-sm border-b border-white/5">
                  <div className="flex">
                    {(['risks', 'revisions', 'conclusion'] as const).map(tab => (
                      <button key={tab} onClick={() => setActiveRightTab(tab)}
                        className={`flex-1 text-[11px] py-2.5 font-medium transition-all border-b-2 ${
                          activeRightTab === tab ? 'border-blue-400 text-blue-400 bg-blue-500/[0.04]' : 'border-transparent text-gold-200/40 hover:text-gold-200/60'
                        }`}>
                        {tab === 'risks' ? '风险清单' : tab === 'revisions' ? '修订建议' : '审查结论'}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="p-4 space-y-3">
                  {/* 风险清单 */}
                  {activeRightTab === 'risks' && (
                    riskList.length > 0 ? riskList.map((risk, i) => (
                      <div key={i} className="rounded-lg bg-white/[0.02] border border-white/5 p-3 hover:border-red-400/15 transition-colors">
                        <div className="flex items-start justify-between gap-2 mb-1.5">
                          <div className="flex items-center gap-1.5">
                            {riskBadge(risk.level)}
                            <span className="text-[11px] font-medium text-gold-200/85">{risk.title}</span>
                          </div>
                          {risk.location && <span className="text-[9px] text-gold-200/25 flex-shrink-0">位置：{risk.location}</span>}
                        </div>
                        <p className="text-[10px] text-gold-200/50 leading-relaxed mb-1.5">{risk.description}</p>
                        {risk.legal_basis && (
                          <p className="text-[10px] text-blue-350/60 mb-1.5"><span className="text-gold-200/35">问题依据：</span>{risk.legal_basis}</p>
                        )}
                        {risk.suggestion && (
                          <div className="text-[10px] text-amber-350/75 bg-amber-400/[0.03] rounded px-2 py-1.5">
                            <span className="text-gold-200/35">建议修改：</span>{risk.suggestion}
                          </div>
                        )}
                      </div>
                    )) : <div className="text-center py-12 text-[11px] text-gold-200/30">{isReviewing ? '正在扫描风险...' : '暂无风险数据'}</div>
                  )}

                  {/* 修订建议 */}
                  {activeRightTab === 'revisions' && (
                    revisionList.length > 0 ? revisionList.map((rev, i) => (
                      <div key={i} className="rounded-lg bg-white/[0.02] border border-white/5 p-3 hover:border-amber-400/15 transition-colors">
                        <div className="flex items-center gap-1.5 mb-1.5">
                          {riskBadge(rev.level)}
                          <span className="text-[11px] font-medium text-gold-200/85">{rev.title}</span>
                          {rev.location && <span className="text-[9px] text-gold-200/25 ml-auto">位置：{rev.location}</span>}
                        </div>
                        <p className="text-[10px] text-gold-200/50 leading-relaxed mb-2">{rev.description}</p>
                        {rev.original_text && (
                          <div className="mb-1.5">
                            <span className="text-[9px] text-red-400/60 block mb-0.5">原文：</span>
                            <p className="text-[10px] text-red-300/50 bg-red-400/[0.03] rounded px-2 py-1.5 line-through decoration-red-400/40">{rev.original_text}</p>
                          </div>
                        )}
                        {rev.suggested_text && (
                          <div>
                            <span className="text-[9px] text-emerald-400/60 block mb-0.5">建议：</span>
                            <p className="text-[10px] text-emerald-300/70 bg-emerald-400/[0.03] rounded px-2 py-1.5">{rev.suggested_text}</p>
                          </div>
                        )}
                      </div>
                    )) : <div className="text-center py-12 text-[11px] text-gold-200/30">{isReviewing ? '等待风险分析完成...' : '暂无修订建议'}</div>
                  )}

                  {/* 审查结论 */}
                  {activeRightTab === 'conclusion' && (
                    conclusion?.overall_assessment ? (
                      <div className="space-y-3">
                        <div className="rounded-lg bg-blue-500/[0.04] border border-blue-400/10 p-3">
                          <h4 className="text-[11px] font-semibold text-blue-350 mb-1.5 flex items-center gap-1.5"><HelpCircle size={12} /> 整体评估</h4>
                          <p className="text-[11px] text-gold-200/65 leading-relaxed">{conclusion.overall_assessment}</p>
                        </div>
                        {conclusion.key_findings && conclusion.key_findings.length > 0 && (
                          <div>
                            <h4 className="text-[11px] font-semibold text-gold-200/60 mb-1.5">关键发现</h4>
                            <ul className="space-y-1">
                              {conclusion.key_findings.map((f, i) => (
                                <li key={i} className="text-[10px] text-gold-200/55 flex items-start gap-1.5"><span className="text-amber-400 mt-0.5">•</span>{f}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {conclusion.must_fix_before_sign && conclusion.must_fix_before_sign.length > 0 && (
                          <div>
                            <h4 className="text-[11px] font-semibold text-red-300/70 mb-1.5">签署前必须修复</h4>
                            <ul className="space-y-1">
                              {conclusion.must_fix_before_sign.map((f, i) => (
                                <li key={i} className="text-[10px] text-red-300/60 flex items-start gap-1.5"><AlertCircle size={10} className="mt-0.5 flex-shrink-0" />{f}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {conclusion.negotiation_priority && conclusion.negotiation_priority.length > 0 && (
                          <div>
                            <h4 className="text-[11px] font-semibold text-amber-350/70 mb-1.5">谈判优先级</h4>
                            <ol className="space-y-1 list-decimal list-inside">
                              {conclusion.negotiation_priority.map((f, i) => (
                                <li key={i} className="text-[10px] text-gold-200/55">{f}</li>
                              ))}
                            </ol>
                          </div>
                        )}
                      </div>
                    ) : <div className="text-center py-12 text-[11px] text-gold-200/30">{isReviewing ? '等待审查完成...' : '暂无审查结论'}</div>
                  )}
                </div>
              </aside>
            </div>

            {/* 底部 - 五栏报告区域 */}
            {reportSections && Object.keys(reportSections).length > 0 && (
              <div className="h-44 border-t border-white/5 bg-[#0c1729]/60 flex-shrink-0">
                <div className="h-full flex flex-col">
                  <div className="h-9 border-b border-white/5 flex items-center justify-between px-4 flex-shrink-0">
                    <div className="flex items-center gap-2"><FileCheck size={13} className="text-gold-200/50" /><span className="text-[11px] font-medium text-gold-200/70">审查报告（精）</span></div>
                    <button className="flex items-center gap-1 text-[10px] text-gold-200/40 hover:text-gold-200/60"><Eye size={10} /> 查看完整报告 <ChevronDown size={10} /></button>
                  </div>
                  <div className="flex-1 overflow-y-auto p-4">
                    <div className="grid grid-cols-5 gap-3 h-full">
                      {[
                        { key: 'summary' as const, num: '一', title: '合同摘要/基本信息' },
                        { key: 'clause_details' as const, num: '二', title: '条款审查详情' },
                        { key: 'risk_summary' as const, num: '三', title: '风险问题汇总' },
                        { key: 'revision_summary' as const, num: '四', title: '修订建议汇总' },
                        { key: 'conclusion' as const, num: '五', title: '结论与建议' },
                      ].map(sec => (
                        <div key={sec.key} className="space-y-1.5 min-h-0">
                          <h4 className="text-[10px] font-semibold text-gold-200/60 flex items-center gap-1">
                            <span className="w-3.5 h-3.5 rounded bg-blue-500/15 text-blue-400 flex items-center justify-center text-[8px]">{sec.num}</span>
                            <span className="truncate">{sec.title}</span>
                          </h4>
                          <ul className="space-y-1 overflow-y-auto max-h-[calc(100%-24px)]">
                            {(reportSections[sec.key] || ['--']).slice(0, 6).map((item, i) => (
                              <li key={i} className="text-[9px] text-gold-200/45 leading-relaxed line-clamp-2 list-disc list-inside">{item}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* 底部操作栏 */}
            {isReviewing && (
              <div className="h-10 border-t border-white/5 flex items-center justify-between px-4 bg-[#0c1729]/80 flex-shrink-0">
                <div className="flex items-center gap-2 text-xs text-gold-200/50">
                  <Loader2 size={14} className="animate-spin text-blue-400" />
                  <span>当前节点：<span className="text-blue-400 font-medium">{NODE_LABELS[currentNode] || currentNode || '准备中'}</span></span>
                </div>
                <button onClick={handleStop} className="text-xs px-3 py-1.5 rounded-lg border border-red-400/30 text-red-400 hover:bg-red-400/10 flex items-center gap-1"><StopCircle size={12} /> 停止审查</button>
              </div>
            )}
          </div>
      </main>
      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}
