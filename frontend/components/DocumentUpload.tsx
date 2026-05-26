'use client'

import { useState, useRef, useCallback } from 'react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'
import {
  FileText, CheckCircle, AlertCircle, Shield,
  Loader2, Plus, Download,
  Search, FileCheck, Eye, HelpCircle, MinusCircle,
  ArrowUpRight, StopCircle, AlertTriangle, X, FileUp
} from 'lucide-react'
import { motion } from 'framer-motion'
import {
  uploadDocument, contractReviewStream, getDocumentContent,
  type StructuredReviewData, type ContractReviewMetadata, type ContractReviewDone
} from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

type FileStatus = 'uploading' | 'uploaded' | 'reviewing' | 'done' | 'error'

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

type ClauseTreeItem = { id: string; label: string; status: 'pass' | 'warning' | 'danger' | 'info'; risk_count: number }
type ClauseDisplay = { title: string; content: string; status: string; tags?: string[]; suggestion?: string; location?: string }
type RiskItem = { level: string; title: string; description: string; location?: string; legal_basis?: string; suggestion?: string }
type RevisionItem = { level: string; title: string; description: string; original_text?: string; suggested_text?: string; location?: string }

function statusIcon(status: string, size = 14) {
  switch (status) {
    case 'pass': return <CheckCircle size={size} className="text-emerald-400" />
    case 'warning': return <AlertTriangle size={size} className="text-amber-400" />
    case 'danger': return <AlertCircle size={size} className="text-red-400" />
    default: return <MinusCircle size={size} className="text-slate-400" />
  }
}

function statusBadge(status: string) {
  const map: Record<string, { bg: string; text: string; label: string }> = {
    pass:     { bg: 'bg-emerald-50', text: 'text-emerald-600', label: '已通过' },
    warning:  { bg: 'bg-amber-50', text: 'text-amber-600', label: '需注意' },
    danger:   { bg: 'bg-red-50',   text: 'text-red-600',   label: '高风险' },
    info:     { bg: 'bg-slate-50',  text: 'text-slate-400',  label: '待审查' },
  }
  const s = map[status] || map.info
  return <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.bg} ${s.text}`}>{s.label}</span>
}

function riskBadge(level: string) {
  if (level.includes('P0') || level.includes('高')) return <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-50 text-red-600 border border-red-200 font-medium">高风险</span>
  if (level.includes('P1') || level.includes('中')) return <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-600 border border-amber-200 font-medium">中风险</span>
  return <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-200">低风险</span>
}

export default function DocumentUpload() {
  const { authed } = useChatStore()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [files, setFiles] = useState<DocFile[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isReviewing, setIsReviewing] = useState(false)
  const [reviewDone, setReviewDone] = useState(false)

  // 审查结果状态（初始为空，由 AI 生成）
  const [caseName, setCaseName] = useState('')
  const [riskLevelLabel, setRiskLevelLabel] = useState('--')
  const [canSign, setCanSign] = useState<string>('待评估')
  const [clauseTree, setClauseTree] = useState<ClauseTreeItem[]>([])
  const [clausesDisplay, setClausesDisplay] = useState<ClauseDisplay[]>([])
  const [riskList, setRiskList] = useState<RiskItem[]>([])
  const [revisionList, setRevisionList] = useState<RevisionItem[]>([])
  const [conclusion, setConclusion] = useState<StructuredReviewData['conclusion']>({})
  const [reportSections, setReportSections] = useState<StructuredReviewData['report_sections']>({})
  const [stats, setStats] = useState({ total_clauses: 0, high_risk: 0, medium_risk: 0, low_risk: 0, passed: 0, completion_rate: 0 })
  const [currentNode, setCurrentNode] = useState('')
  const [contractText, setContractText] = useState('') // 合同原文
  const [activeMiddleTab, setActiveMiddleTab] = useState<'original' | 'review'>('original') // 中间区域标签

  const [activeRightTab, setActiveRightTab] = useState<'risks' | 'revisions' | 'conclusion'>('risks')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [showHighOnly, setShowHighOnly] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 是否已上传文件并开始审查
  const hasReviewData = reviewDone || isReviewing

  const handleFiles = useCallback(async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    if (!authed) { setError('请先登录'); return }
    setError(null)

    const f = fileList[0] // 只取第一个文件
    const ext = f.name.split('.').pop()?.toUpperCase() || 'FILE'
    const localId = Date.now().toString() + Math.random().toString(36).slice(2)
    const docFile: DocFile = { id: localId, name: f.name, size: (f.size / 1024).toFixed(1) + ' KB', status: 'uploading', type: ext }
    setFiles([docFile])

    try {
      // 上传文件
      const result = await uploadDocument(f)
      setFiles(prev => prev.map(item => item.id === localId ? { ...item, status: 'uploaded', serverId: result.id } : item))

      // 获取文件内容
      let contractText = ''
      if (result.id) {
        contractText = await getDocumentContent(result.id)
      }
      if (!contractText?.trim()) contractText = `合同文件：${f.name}`
      setContractText(contractText) // 保存合同原文

      // 自动开始审查
      await startContractReview(localId, contractText, f.name)
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败')
      setFiles(prev => prev.map(item => item.id === localId ? { ...item, status: 'error' } : item))
    }
  }, [authed])

  const startContractReview = async (docId: string, contractText: string, fileName: string) => {
    setIsReviewing(true); setReviewDone(false); setError(null)
    setCurrentNode('')
    setClauseTree([]); setClausesDisplay([]); setRiskList([]); setRevisionList([])
    setConclusion({}); setReportSections({})
    setStats({ total_clauses: 0, high_risk: 0, medium_risk: 0, low_risk: 0, passed: 0, completion_rate: 0 })
    setCaseName(fileName.replace(/\.[^.]+$/, '') + ' 审查'); setRiskLevelLabel('--'); setCanSign('待评估')

    setFiles(prev => prev.map(item => item.id === docId ? { ...item, status: 'reviewing' } : item))

    const abortController = new AbortController(); abortRef.current = abortController

    try {
      for await (const event of contractReviewStream({ contract_text: contractText, user_position: '乙方', review_stance: '常规' }, abortController.signal)) {
        if (event.type === 'chunk') {
          const chunk = event.data as { node: string; content: string }
          setCurrentNode(chunk.node)
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
    } finally {
      setIsReviewing(false); abortRef.current = null
      setFiles(prev => prev.map(f => f.status === 'reviewing' ? { ...f, status: 'done' } : f))
    }
  }

  const handleStop = () => { if (abortRef.current) { abortRef.current.abort(); setIsReviewing(false); setReviewDone(true) } }

  const handleReset = () => {
    setFiles([]); setError(null); setIsReviewing(false); setReviewDone(false)
    setClauseTree([]); setClausesDisplay([]); setRiskList([]); setRevisionList([])
    setConclusion({}); setReportSections({}); setStats({ total_clauses: 0, high_risk: 0, medium_risk: 0, low_risk: 0, passed: 0, completion_rate: 0 })
    setCaseName(''); setRiskLevelLabel('--'); setCanSign('待评估'); setCurrentNode('')
    setContractText(''); setActiveMiddleTab('original')
  }

  const handleExportReport = () => {
    const content = conclusion?.overall_assessment
      || (reportSections && Object.keys(reportSections).length > 0
        ? Object.entries(reportSections).map(([key, items]) => `${key}:\n${(items as string[]).join('\n')}`).join('\n\n')
        : riskList.map(r => `[${r.level}] ${r.title}: ${r.description}`).join('\n'))
      || '暂无报告内容'
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `审查报告_${new Date().toISOString().slice(0,10)}.txt`; a.click()
    URL.revokeObjectURL(url)
  }

  const handleDrag = (e: React.DragEvent) => { e.preventDefault(); e.stopPropagation(); setDragActive(e.type === 'dragenter' || e.type === 'dragover') }

  const filteredClauses = clausesDisplay.filter(c => !searchKeyword || c.title.includes(searchKeyword) || c.content.includes(searchKeyword))

  const CAN_SIGN_STYLE: Record<string, { bg: string; text: string }> = {
    '可签': { bg: 'bg-emerald-50', text: 'text-emerald-600' },
    '有条件可签': { bg: 'bg-amber-50', text: 'text-amber-600' },
    '不建议签': { bg: 'bg-red-50', text: 'text-red-600' },
    '待评估': { bg: 'bg-slate-50', text: 'text-slate-400' },
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />

      <main className="flex-1 flex flex-col bg-white overflow-hidden">
        {/* 顶部标题栏 */}
        <header className="h-14 border-b border-gray-200 flex items-center justify-between px-6 bg-white flex-shrink-0 z-10">
          <div className="flex items-center gap-3">
            <Shield size={20} className="text-blue-600" />
            <h1 className="text-base font-semibold text-slate-800">合同审查工作台</h1>
            {caseName && (
              <>
                <span className="text-sm text-slate-500 font-medium">{caseName}</span>
                <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                  riskLevelLabel.includes('高') ? 'bg-red-50 text-red-600 border border-red-200' :
                  riskLevelLabel.includes('中高') ? 'bg-orange-50 text-orange-600 border border-orange-200' :
                  riskLevelLabel.includes('中') ? 'bg-amber-50 text-amber-600 border border-amber-200' :
                  'bg-emerald-50 text-emerald-600 border border-emerald-200'
                }`}>综合风险：{riskLevelLabel}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${CAN_SIGN_STYLE[canSign]?.bg || 'bg-slate-50'} ${CAN_SIGN_STYLE[canSign]?.text || 'text-slate-400'}`}>{canSign}</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => fileInputRef.current?.click()} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs hover:bg-blue-700 transition-colors"><Plus size={12} /> 上传合同</button>
            {hasReviewData && <button onClick={handleExportReport} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-50 border border-gray-200 text-blue-500 text-xs hover:bg-slate-100 transition-colors"><Download size={12} /> 导出报告</button>}
            {hasReviewData && <button onClick={handleReset} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-50 border border-gray-200 text-slate-500 text-xs hover:bg-slate-100 transition-colors"><X size={12} /> 重新上传</button>}
          </div>
        </header>

        <input ref={fileInputRef} type="file" accept=".pdf,.doc,.docx,.txt" className="hidden" onChange={e => handleFiles(e.target.files)} />

        {/* 未上传时显示上传区域 */}
        {!hasReviewData && files.length === 0 && (
          <div className="flex-1 flex items-center justify-center p-8">
            <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
              className={`w-full max-w-xl border-2 border-dashed rounded-2xl p-12 text-center transition-colors ${
                dragActive ? 'border-blue-400 bg-blue-50' : 'border-gray-300 bg-slate-50 hover:border-blue-300 hover:bg-blue-50/50'
              }`}
              onDragEnter={handleDrag} onDragOver={handleDrag} onDragLeave={handleDrag} onDrop={e => { handleDrag(e); handleFiles(e.dataTransfer.files) }}
            >
              <div className="w-16 h-16 rounded-2xl bg-blue-100 flex items-center justify-center mx-auto mb-5">
                <FileUp size={28} className="text-blue-600" />
              </div>
              <h2 className="text-lg font-semibold text-slate-700 mb-2">上传合同文件</h2>
              <p className="text-sm text-slate-500 mb-6">支持 PDF、Word、TXT 格式，上传后 AI 将自动进行合同审查</p>
              <button onClick={() => fileInputRef.current?.click()}
                className="px-6 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm">
                选择文件上传
              </button>
              <p className="text-xs text-slate-400 mt-4">或将文件拖拽到此处</p>
            </motion.div>
          </div>
        )}

        {/* 上传中 */}
        {files.length > 0 && !hasReviewData && (
          <div className="flex-1 flex items-center justify-center p-8">
            <div className="text-center">
              <Loader2 size={32} className="animate-spin text-blue-600 mx-auto mb-4" />
              <h3 className="text-base font-medium text-slate-700 mb-1">正在上传合同文件...</h3>
              <p className="text-sm text-slate-500">{files[0].name} ({files[0].size})</p>
              {error && <p className="text-sm text-red-500 mt-2">{error}</p>}
            </div>
          </div>
        )}

        {/* 审查中 / 审查完成 - 显示三栏布局 */}
        {hasReviewData && (
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="flex-1 flex overflow-hidden min-h-0">

              {/* 左侧 - 合同结构树 */}
              <aside className="w-52 border-r border-gray-200 flex-shrink-0 overflow-y-auto bg-slate-50">
                <div className="p-4 space-y-1">
                  <div className="flex items-center justify-between mb-3 pb-2 border-b border-gray-200">
                    <span className="text-xs font-semibold text-slate-600">合同结构</span>
                    <span className="text-[10px] text-emerald-600">{stats.completion_rate}%</span>
                  </div>

                  {clauseTree.length > 0 ? clauseTree.map(item => (
                    <button key={item.id} className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left hover:bg-slate-50 transition-colors group">
                      {statusIcon(item.status)}
                      <span className={`text-xs flex-1 truncate ${item.status === 'danger' ? 'text-red-600' : item.status === 'warning' ? 'text-amber-600' : 'text-slate-600 group-hover:text-slate-800'}`}>
                        {item.label}
                      </span>
                      {item.risk_count > 0 && (
                        <span className={`text-[10px] w-4 h-4 rounded-full flex items-center justify-center ${item.status === 'danger' ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-600'}`}>
                          {item.risk_count}
                        </span>
                      )}
                    </button>
                  )) : (
                    isReviewing ? (
                      <div className="space-y-2">
                        {[1,2,3,4,5,6].map(i => (
                          <div key={i} className="flex items-center gap-2.5 px-2.5 py-2 animate-pulse">
                            <div className="w-3.5 h-3.5 rounded-full bg-slate-100" /><div className="h-2.5 flex-1 rounded bg-slate-100" />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[11px] text-slate-400 text-center py-8">等待条款提取...</p>
                    )
                  )}
                </div>

                {stats.total_clauses > 0 && (
                  <div className="mx-4 mb-4 mt-2 pt-3 border-t border-gray-200 space-y-2">
                    <h4 className="text-[11px] font-semibold text-slate-500">审查概览</h4>
                    <div className="grid grid-cols-2 gap-1.5 text-[10px]">
                      <div className="flex justify-between"><span className="text-slate-500">共识别</span><span className="text-slate-600">{stats.total_clauses} 个条款</span></div>
                      <div className="flex justify-between"><span className="text-slate-500">发现</span><span className="text-red-600">{stats.high_risk + stats.medium_risk + stats.low_risk} 处风险</span></div>
                      <div className="flex justify-between"><span className="text-red-600">● 高风险</span><span>{stats.high_risk} 处</span></div>
                      <div className="flex justify-between"><span className="text-amber-600">● 中风险</span><span>{stats.medium_risk} 处</span></div>
                      <div className="flex justify-between"><span className="text-blue-600">● 低风险</span><span>{stats.low_risk} 处</span></div>
                      <div className="flex justify-between"><span className="text-emerald-600">● 已通过</span><span>{stats.passed} 处</span></div>
                    </div>
                    <div className="pt-2">
                      <div className="flex justify-between text-[10px] mb-1"><span className="text-slate-500">审查完成度</span><span className="text-slate-500">{stats.completion_rate}%</span></div>
                      <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
                        <motion.div initial={{ width: 0 }} animate={{ width: `${stats.completion_rate}%` }} transition={{ duration: 0.8 }}
                          className={`h-full rounded-full ${stats.completion_rate >= 80 ? 'bg-emerald-500' : stats.completion_rate >= 50 ? 'bg-amber-500' : 'bg-red-500'}`} />
                      </div>
                    </div>
                  </div>
                )}
              </aside>

              {/* 中间 - 合同原文 + 审查结果 */}
              <section className="flex-1 flex flex-col min-w-0 overflow-hidden">
                <div className="h-10 border-b border-gray-200 flex items-center justify-between px-4 flex-shrink-0">
                  <div className="flex items-center gap-1">
                    <button onClick={() => setActiveMiddleTab('original')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t text-xs font-medium transition-colors ${
                        activeMiddleTab === 'original' ? 'text-blue-600 bg-blue-50 border-b-2 border-blue-500' : 'text-slate-500 hover:text-slate-600'
                      }`}>
                      <FileText size={13} /> 合同原文
                    </button>
                    <button onClick={() => setActiveMiddleTab('review')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t text-xs font-medium transition-colors ${
                        activeMiddleTab === 'review' ? 'text-blue-600 bg-blue-50 border-b-2 border-blue-500' : 'text-slate-500 hover:text-slate-600'
                      }`}>
                      <FileCheck size={13} /> 审查结果
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    {activeMiddleTab === 'review' && (
                      <>
                        <div className="relative">
                          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                          <input value={searchKeyword} onChange={e => setSearchKeyword(e.target.value)}
                                 placeholder="搜索条款内容" className="text-[10px] pl-7 pr-3 py-1 rounded-md bg-slate-50 border border-gray-200 text-slate-600 placeholder:text-slate-400 focus:outline-none focus:border-blue-300 w-36" />
                        </div>
                        <label className="flex items-center gap-1 text-[10px] text-slate-500 cursor-pointer select-none">
                          <input type="checkbox" checked={showHighOnly} onChange={e => setShowHighOnly(e.target.checked)} className="rounded border-gray-300" /> 仅高危
                        </label>
                      </>
                    )}
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4">
                  {error && <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-600 text-xs mb-3">{error}</div>}

                  {/* 合同原文标签 */}
                  {activeMiddleTab === 'original' && (
                    <div className="space-y-1">
                      {contractText ? contractText.split('\n').map((line, i) => {
                        // 检查该行是否被风险标注
                        const relatedRisk = riskList.find(r =>
                          r.location && line.includes(r.location.replace(/位置：/, ''))
                        )
                        return (
                          <div key={i} className={`flex items-start gap-2 group ${relatedRisk ? 'bg-red-50/50 -mx-2 px-2 rounded' : ''}`}>
                            {relatedRisk && (
                              <div className="flex-shrink-0 mt-1">
                                <AlertTriangle size={12} className="text-red-500" />
                              </div>
                            )}
                            <p className={`text-sm leading-relaxed whitespace-pre-wrap break-all ${
                              line.trim() === '' ? 'h-3' :
                              line.match(/^(第[一二三四五六七八九十]+[条章节部分编]|合同|协议|甲方|乙方|甲方|乙方|签署|盖章|日期)/) ? 'font-semibold text-slate-800 mt-3' :
                              'text-slate-600'
                            }`}>{line}</p>
                          </div>
                        )
                      }) : (
                        <div className="flex items-center justify-center py-20 text-slate-400 text-sm">暂无合同原文</div>
                      )}
                    </div>
                  )}

                  {/* 审查结果标签 */}
                  {activeMiddleTab === 'review' && (
                    <div className="space-y-3">
                      {filteredClauses.length > 0 ? filteredClauses.filter(c => !showHighOnly || c.status === 'danger').map((clause, i) => (
                        <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                          className={`rounded-xl border p-4 ${
                            clause.status === 'danger' ? 'bg-red-50 border-red-200' :
                            clause.status === 'warning' ? 'bg-amber-50 border-amber-200' :
                            clause.status === 'pass' ? 'bg-emerald-50 border-emerald-200' :
                            'bg-white border-gray-200'
                          }`}>
                          <div className="flex items-start justify-between gap-3 mb-2">
                            <h3 className={`text-xs font-semibold ${clause.status === 'danger' ? 'text-red-600' : clause.status === 'warning' ? 'text-amber-600' : 'text-slate-600'}`}>
                              {clause.title}
                            </h3>
                            <div className="flex items-center gap-1.5 flex-shrink-0">
                              {statusBadge(clause.status)}
                              {clause.location && <span className="text-[9px] text-slate-300">位置：{clause.location}</span>}
                            </div>
                          </div>
                          <p className="text-[11px] text-slate-500 leading-relaxed whitespace-pre-wrap mb-2.5">{clause.content}</p>
                          {clause.tags && clause.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mb-2">
                              {clause.tags.map((tag, ti) => (
                                <span key={ti} className="text-[10px] px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200">{tag}</span>
                              ))}
                            </div>
                          )}
                          {clause.suggestion && (
                            <div className="flex items-start gap-1.5 text-[10px] text-amber-600 bg-amber-50 rounded-md px-2.5 py-1.5">
                              <ArrowUpRight size={11} className="mt-0.5 flex-shrink-0" />
                              <span>建议修改：{clause.suggestion}</span>
                            </div>
                          )}
                        </motion.div>
                      )) : isReviewing ? (
                        <div className="flex items-center justify-center py-20 gap-3 text-slate-400">
                          <Loader2 size={18} className="animate-spin text-blue-600" />
                          <span className="text-sm">正在提取条款并扫描风险...</span>
                        </div>
                      ) : (
                        <div className="flex items-center justify-center py-20 text-slate-400 text-sm">暂无条款数据</div>
                      )}
                    </div>
                  )}
                </div>
              </section>

              {/* 右侧 - 三标签面板 */}
              <aside className="w-80 border-l border-gray-200 flex-shrink-0 overflow-y-auto bg-slate-50">
                <div className="sticky top-0 z-10 bg-white backdrop-blur-sm border-b border-gray-200">
                  <div className="flex">
                    {(['risks', 'revisions', 'conclusion'] as const).map(tab => (
                      <button key={tab} onClick={() => setActiveRightTab(tab)}
                        className={`flex-1 text-[11px] py-2.5 font-medium transition-all border-b-2 ${
                          activeRightTab === tab ? 'border-blue-500 text-blue-600 bg-blue-50' : 'border-transparent text-slate-500 hover:text-slate-600'
                        }`}>
                        {tab === 'risks' ? '风险清单' : tab === 'revisions' ? '修订建议' : '审查结论'}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="p-4 space-y-3">
                  {activeRightTab === 'risks' && (
                    riskList.length > 0 ? riskList.map((risk, i) => (
                      <div key={i} className="rounded-lg bg-white border border-gray-200 p-3 hover:border-red-200 transition-colors">
                        <div className="flex items-start justify-between gap-2 mb-1.5">
                          <div className="flex items-center gap-1.5">
                            {riskBadge(risk.level)}
                            <span className="text-[11px] font-medium text-slate-700">{risk.title}</span>
                          </div>
                          {risk.location && <span className="text-[9px] text-slate-300 flex-shrink-0">位置：{risk.location}</span>}
                        </div>
                        <p className="text-[10px] text-slate-500 leading-relaxed mb-1.5">{risk.description}</p>
                        {risk.legal_basis && <p className="text-[10px] text-blue-500 mb-1.5"><span className="text-slate-400">问题依据：</span>{risk.legal_basis}</p>}
                        {risk.suggestion && (
                          <div className="text-[10px] text-amber-600 bg-amber-50 rounded px-2 py-1.5">
                            <span className="text-slate-400">建议修改：</span>{risk.suggestion}
                          </div>
                        )}
                      </div>
                    )) : <div className="text-center py-12 text-[11px] text-slate-400">{isReviewing ? '正在扫描风险...' : '暂无风险数据'}</div>
                  )}

                  {activeRightTab === 'revisions' && (
                    revisionList.length > 0 ? revisionList.map((rev, i) => (
                      <div key={i} className="rounded-lg bg-white border border-gray-200 p-3 hover:border-amber-200 transition-colors">
                        <div className="flex items-center gap-1.5 mb-1.5">
                          {riskBadge(rev.level)}
                          <span className="text-[11px] font-medium text-slate-700">{rev.title}</span>
                          {rev.location && <span className="text-[9px] text-slate-300 ml-auto">位置：{rev.location}</span>}
                        </div>
                        <p className="text-[10px] text-slate-500 leading-relaxed mb-2">{rev.description}</p>
                        {rev.original_text && (
                          <div className="mb-1.5">
                            <span className="text-[9px] text-red-500 block mb-0.5">原文：</span>
                            <p className="text-[10px] text-red-500 bg-red-50 rounded px-2 py-1.5 line-through decoration-red-300">{rev.original_text}</p>
                          </div>
                        )}
                        {rev.suggested_text && (
                          <div>
                            <span className="text-[9px] text-emerald-600 block mb-0.5">建议：</span>
                            <p className="text-[10px] text-emerald-600 bg-emerald-50 rounded px-2 py-1.5">{rev.suggested_text}</p>
                          </div>
                        )}
                      </div>
                    )) : <div className="text-center py-12 text-[11px] text-slate-400">{isReviewing ? '等待风险分析完成...' : '暂无修订建议'}</div>
                  )}

                  {activeRightTab === 'conclusion' && (
                    conclusion?.overall_assessment ? (
                      <div className="space-y-3">
                        <div className="rounded-lg bg-blue-50 border border-blue-200 p-3">
                          <h4 className="text-[11px] font-semibold text-blue-600 mb-1.5 flex items-center gap-1.5"><HelpCircle size={12} /> 整体评估</h4>
                          <p className="text-[11px] text-slate-600 leading-relaxed">{conclusion.overall_assessment}</p>
                        </div>
                        {conclusion.key_findings?.length && (
                          <div>
                            <h4 className="text-[11px] font-semibold text-slate-600 mb-1.5">关键发现</h4>
                            <ul className="space-y-1">
                              {conclusion.key_findings.map((f, i) => <li key={i} className="text-[10px] text-slate-500 flex items-start gap-1.5"><span className="text-amber-600 mt-0.5">•</span>{f}</li>)}
                            </ul>
                          </div>
                        )}
                        {conclusion.must_fix_before_sign?.length && (
                          <div>
                            <h4 className="text-[11px] font-semibold text-red-600 mb-1.5">签署前必须修复</h4>
                            <ul className="space-y-1">
                              {conclusion.must_fix_before_sign.map((f, i) => <li key={i} className="text-[10px] text-red-500 flex items-start gap-1.5"><AlertCircle size={10} className="mt-0.5 flex-shrink-0" />{f}</li>)}
                            </ul>
                          </div>
                        )}
                        {conclusion.negotiation_priority?.length && (
                          <div>
                            <h4 className="text-[11px] font-semibold text-amber-600 mb-1.5">谈判优先级</h4>
                            <ol className="space-y-1 list-decimal list-inside">
                              {conclusion.negotiation_priority.map((f, i) => <li key={i} className="text-[10px] text-slate-500">{f}</li>)}
                            </ol>
                          </div>
                        )}
                      </div>
                    ) : <div className="text-center py-12 text-[11px] text-slate-400">{isReviewing ? '等待审查完成...' : '暂无审查结论'}</div>
                  )}
                </div>
              </aside>
            </div>

            {/* 底部报告区域 */}
            {reportSections && Object.keys(reportSections).length > 0 && (
              <div className="h-44 border-t border-gray-200 bg-slate-50 flex-shrink-0">
                <div className="h-full flex flex-col">
                  <div className="h-9 border-b border-gray-200 flex items-center justify-between px-4 flex-shrink-0">
                    <div className="flex items-center gap-2"><FileCheck size={13} className="text-slate-500" /><span className="text-[11px] font-medium text-slate-500">审查报告</span></div>
                    <button onClick={handleExportReport} className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-600"><Eye size={10} /> 导出完整报告</button>
                  </div>
                  <div className="flex-1 overflow-y-auto p-4">
                    <div className="grid grid-cols-5 gap-3 h-full">
                      {[
                        { key: 'summary' as const, num: '一', title: '合同摘要' },
                        { key: 'clause_details' as const, num: '二', title: '条款审查详情' },
                        { key: 'risk_summary' as const, num: '三', title: '风险问题汇总' },
                        { key: 'revision_summary' as const, num: '四', title: '修订建议汇总' },
                        { key: 'conclusion' as const, num: '五', title: '结论与建议' },
                      ].map(sec => (
                        <div key={sec.key} className="space-y-1.5 min-h-0">
                          <h4 className="text-[10px] font-semibold text-slate-600 flex items-center gap-1">
                            <span className="w-3.5 h-3.5 rounded bg-blue-50 text-blue-600 flex items-center justify-center text-[8px]">{sec.num}</span>
                            <span className="truncate">{sec.title}</span>
                          </h4>
                          <ul className="space-y-1 overflow-y-auto max-h-[calc(100%-24px)]">
                            {(reportSections[sec.key] || ['--']).slice(0, 6).map((item, i) => (
                              <li key={i} className="text-[9px] text-slate-500 leading-relaxed line-clamp-2 list-disc list-inside">{item}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* 审查进度条 */}
            {isReviewing && (
              <div className="h-10 border-t border-gray-200 flex items-center justify-between px-4 bg-white flex-shrink-0">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Loader2 size={14} className="animate-spin text-blue-600" />
                  <span>当前节点：<span className="text-blue-600 font-medium">{NODE_LABELS[currentNode] || currentNode || '准备中'}</span></span>
                </div>
                <button onClick={handleStop} className="text-xs px-3 py-1.5 rounded-lg border border-red-300 text-red-600 hover:bg-red-50 flex items-center gap-1"><StopCircle size={12} /> 停止审查</button>
              </div>
            )}
          </div>
        )}
      </main>
      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}
