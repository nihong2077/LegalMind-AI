import { FileText, Scale, Gavel, CheckCircle, AlertCircle, Info, MessageSquare, Search, ListChecks } from 'lucide-react'

// ============================================================
// 类型定义
// ============================================================

interface ApplicableLaw {
  law_name: string
  article_number: string
  article_content: string
  relevance: string
}

interface FactFinding {
  fact: string
  evidence_basis: string
  certainty: string
}

/** 法官裁决 JSON（IRAC 结构） */
interface VerdictData {
  issue?: { legal_questions: string[]; dispute_nature: string }
  rule?: { applicable_laws: ApplicableLaw[]; judicial_interpretations: string[] }
  application?: {
    fact_finding: FactFinding[]
    legal_analysis: string
    fault_determination: { plaintiff_fault_ratio: number; defendant_fault_ratio: number; reasoning: string }
  }
  conclusion?: {
    verdict: string
    specific_orders: string[]
    damage_calculation?: { total_amount: number; breakdown: string }
    litigation_costs: string
    enforcement_period: string
  }
  dissenting_opinion?: string
}

/** 法官开庭 JSON */
interface OpeningData {
  opening_statement?: string
  focus_points?: Array<{ id: string; description: string; type: string; status: string; plaintiff_position: string; defendant_position: string }>
  facts_to_clarify?: string[]
  debate_direction?: string
}

/** 法庭调查 JSON */
interface InvestigationData {
  investigation_questions?: Array<{ target: string; question: string; purpose: string; related_focus: string }>
  facts_confirmed?: string[]
  facts_disputed?: string[]
  evidence_gaps?: string[]
}

/** 辩论点评 JSON */
interface EvaluationData {
  round_evaluation?: {
    plaintiff_strength?: string
    plaintiff_weakness?: string
    defendant_strength?: string
    defendant_weakness?: string
  }
  focus_updates?: Array<{ focus_id: string; status: string; progress: string }>
  facts_established?: string[]
  legal_issues_remaining?: string[]
  evidence_needed?: boolean
  evidence_gap_description?: string
  next_round_guidance?: string
  judge_comment?: string
}

// ============================================================
// 工具函数
// ============================================================

/** 清理 LLM 输出中的 Markdown 标记 */
function cleanMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*\*(.+?)\*\*\*/g, '$1')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^---+$/gm, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** 尝试从文本中提取 JSON（支持中文引号修复、混合文本提取） */
function tryParseJson(content: string): Record<string, unknown> | null {
  // 直接解析
  try {
    const parsed = JSON.parse(content)
    if (typeof parsed === 'object' && parsed !== null) return parsed
  } catch { /* 继续 */ }
  // 尝试从 ```json ... ``` 中提取
  if (content.includes('```json')) {
    const match = content.match(/```json\s*([\s\S]*?)```/)
    if (match) {
      try { return JSON.parse(match[1].trim()) } catch { /* 继续 */ }
    }
  }
  // 尝试从 ``` ... ``` 中提取
  if (content.includes('```')) {
    const match = content.match(/```\s*([\s\S]*?)```/)
    if (match) {
      try { return JSON.parse(match[1].trim()) } catch { /* 继续 */ }
    }
  }
  // 尝试提取 { ... } 块（贪婪匹配，从第一个 { 到最后一个 }）
  const jsonMatch = content.match(/\{[\s\S]*\}/)
  if (jsonMatch) {
    try { return JSON.parse(jsonMatch[0]) } catch { /* 继续 */ }
    // 尝试修复中文引号后解析
    const fixed = jsonMatch[0]
      .replace(/[\u201c\u201d]/g, '"')  // 中文双引号 ""
      .replace(/[\u2018\u2019]/g, "'")  // 中文单引号 ''
      .replace(/，/g, ',')               // 中文逗号
      .replace(/：/g, ':')               // 中文冒号
    try { return JSON.parse(fixed) } catch { /* 继续 */ }
  }
  return null
}

/** 从混合文本中提取 JSON 和前后文本 */
function extractJsonAndText(content: string): { beforeText: string; json: Record<string, unknown> | null; afterText: string } {
  // 先尝试直接解析
  const directParse = tryParseJson(content)
  if (directParse) return { beforeText: '', json: directParse, afterText: '' }

  // 尝试从 ```json ... ``` 中提取
  const codeBlockMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/)
  if (codeBlockMatch && codeBlockMatch.index !== undefined) {
    const jsonStr = codeBlockMatch[1].trim()
    try {
      const parsed = JSON.parse(jsonStr)
      if (typeof parsed === 'object' && parsed !== null) {
        const beforeText = content.slice(0, codeBlockMatch.index).trim()
        const afterText = content.slice(codeBlockMatch.index + codeBlockMatch[0].length).trim()
        return { beforeText, json: parsed, afterText }
      }
    } catch { /* 继续 */ }
  }

  // 尝试提取 { ... } 块（贪婪匹配）
  const jsonMatch = content.match(/\{[\s\S]*\}/)
  if (jsonMatch && jsonMatch.index !== undefined) {
    const jsonStr = jsonMatch[0]
    try {
      const parsed = JSON.parse(jsonStr)
      if (typeof parsed === 'object' && parsed !== null) {
        const beforeText = content.slice(0, jsonMatch.index).trim()
        const afterText = content.slice(jsonMatch.index + jsonStr.length).trim()
        return { beforeText, json: parsed, afterText }
      }
    } catch { /* 继续 */ }
    // 尝试修复中文引号后解析
    const fixed = jsonStr
      .replace(/[\u201c\u201d]/g, '"')
      .replace(/[\u2018\u2019]/g, "'")
      .replace(/，/g, ',')
      .replace(/：/g, ':')
    try {
      const parsed = JSON.parse(fixed)
      if (typeof parsed === 'object' && parsed !== null) {
        const beforeText = content.slice(0, jsonMatch.index).trim()
        const afterText = content.slice(jsonMatch.index + jsonStr.length).trim()
        return { beforeText, json: parsed, afterText }
      }
    } catch { /* 继续 */ }
  }

  return { beforeText: content, json: null, afterText: '' }
}

// ============================================================
// 通用渲染子组件
// ============================================================

function SectionCard({ icon: Icon, title, color, children }: {
  icon: React.ElementType; title: string; color: { bg: string; border: string; text: string; icon: string }
  children: React.ReactNode
}) {
  return (
    <div className={`rounded-xl ${color.bg} border ${color.border} p-4`}>
      <div className="flex items-center gap-2 mb-3">
        <Icon size={14} className={color.icon} />
        <span className={`text-xs font-semibold ${color.text}`}>{title}</span>
      </div>
      {children}
    </div>
  )
}

function Tag({ text, colorClass }: { text: string; colorClass: string }) {
  return <span className={`text-[9px] px-1.5 py-0.5 rounded ${colorClass}`}>{text}</span>
}

function ListItem({ index, children, color }: { index?: number; children: React.ReactNode; color: string }) {
  return (
    <li className="flex items-start gap-2 text-xs leading-relaxed">
      {index !== undefined && (
        <span className={`w-5 h-5 rounded-full ${color} flex items-center justify-center flex-shrink-0 text-[9px] font-medium`}>{index}</span>
      )}
      <span className="flex-1">{children}</span>
    </li>
  )
}

// ============================================================
// 纯文本渲染（非 JSON 或解析失败时）
// ============================================================

function PlainTextRenderer({ content }: { content: string }) {
  const cleaned = cleanMarkdown(content)
  // 如果清理后内容很短或看起来像 JSON 残留，尝试格式化
  if (cleaned.startsWith('{') || cleaned.startsWith('[')) {
    return (
      <div className="rounded-xl bg-slate-50 border border-slate-200 p-4">
        <pre className="text-[11px] text-slate-600 whitespace-pre-wrap break-all font-mono">{cleaned}</pre>
      </div>
    )
  }
  return (
    <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
      {cleaned}
    </div>
  )
}

// ============================================================
// 法官开庭渲染
// ============================================================

function OpeningRenderer({ data }: { data: OpeningData }) {
  const color = { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', icon: 'text-blue-600' }
  return (
    <div className="space-y-3">
      {data.opening_statement && (
        <SectionCard icon={Gavel} title="开庭致辞" color={color}>
          <p className="text-xs text-blue-800 leading-relaxed">{data.opening_statement}</p>
        </SectionCard>
      )}
      {data.focus_points && data.focus_points.length > 0 && (
        <SectionCard icon={AlertCircle} title="争议焦点" color={{ bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', icon: 'text-amber-600' }}>
          <div className="space-y-2">
            {data.focus_points.map((fp, i) => (
              <div key={i} className="bg-amber-100/50 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="w-5 h-5 rounded-full bg-amber-200 text-amber-800 flex items-center justify-center text-[9px] font-medium">{fp.id || i + 1}</span>
                  <span className="text-xs font-medium text-amber-800">{fp.description}</span>
                  <Tag text={fp.type} colorClass="bg-amber-200 text-amber-700" />
                </div>
                <div className="grid grid-cols-2 gap-2 mt-1">
                  <div className="text-[10px] text-amber-700"><span className="font-medium">原告：</span>{fp.plaintiff_position}</div>
                  <div className="text-[10px] text-amber-700"><span className="font-medium">被告：</span>{fp.defendant_position}</div>
                </div>
              </div>
            ))}
          </div>
        </SectionCard>
      )}
      {data.facts_to_clarify && data.facts_to_clarify.length > 0 && (
        <SectionCard icon={Search} title="需查明事实" color={{ bg: 'bg-cyan-50', border: 'border-cyan-200', text: 'text-cyan-700', icon: 'text-cyan-600' }}>
          <ul className="space-y-1.5">
            {data.facts_to_clarify.map((f, i) => (
              <ListItem key={i} index={i + 1} color="bg-cyan-200 text-cyan-800">
                <span className="text-cyan-700">{f}</span>
              </ListItem>
            ))}
          </ul>
        </SectionCard>
      )}
      {data.debate_direction && (
        <SectionCard icon={MessageSquare} title="辩论指引" color={{ bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', icon: 'text-slate-500' }}>
          <p className="text-xs text-slate-600 leading-relaxed">{data.debate_direction}</p>
        </SectionCard>
      )}
    </div>
  )
}

// ============================================================
// 法庭调查渲染
// ============================================================

function InvestigationRenderer({ data }: { data: InvestigationData }) {
  return (
    <div className="space-y-3">
      {data.investigation_questions && data.investigation_questions.length > 0 && (
        <SectionCard icon={Search} title="调查追问" color={{ bg: 'bg-cyan-50', border: 'border-cyan-200', text: 'text-cyan-700', icon: 'text-cyan-600' }}>
          <div className="space-y-2">
            {data.investigation_questions.map((q, i) => (
              <div key={i} className="bg-cyan-100/50 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <Tag text={q.target} colorClass="bg-cyan-200 text-cyan-700" />
                  {q.related_focus && <Tag text={q.related_focus} colorClass="bg-cyan-100 text-cyan-600" />}
                </div>
                <p className="text-xs text-cyan-800 font-medium mb-1">{q.question}</p>
                {q.purpose && <p className="text-[10px] text-cyan-600">目的：{q.purpose}</p>}
              </div>
            ))}
          </div>
        </SectionCard>
      )}
      {data.facts_confirmed && data.facts_confirmed.length > 0 && (
        <SectionCard icon={CheckCircle} title="无争议事实" color={{ bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', icon: 'text-emerald-600' }}>
          <ul className="space-y-1.5">
            {data.facts_confirmed.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-emerald-700">
                <CheckCircle size={12} className="text-emerald-500 mt-0.5 flex-shrink-0" />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
      {data.facts_disputed && data.facts_disputed.length > 0 && (
        <SectionCard icon={AlertCircle} title="争议事实" color={{ bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', icon: 'text-amber-600' }}>
          <ul className="space-y-1.5">
            {data.facts_disputed.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-amber-700">
                <AlertCircle size={12} className="text-amber-500 mt-0.5 flex-shrink-0" />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
      {data.evidence_gaps && data.evidence_gaps.length > 0 && (
        <SectionCard icon={AlertCircle} title="证据薄弱环节" color={{ bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', icon: 'text-red-500' }}>
          <ul className="space-y-1.5">
            {data.evidence_gaps.map((g, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-red-600">
                <AlertCircle size={12} className="text-red-400 mt-0.5 flex-shrink-0" />
                <span>{g}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  )
}

// ============================================================
// 辩论点评渲染
// ============================================================

function EvaluationRenderer({ data }: { data: EvaluationData }) {
  const statusColor: Record<string, string> = {
    resolved: 'bg-emerald-100 text-emerald-700',
    partially_resolved: 'bg-amber-100 text-amber-700',
    unresolved: 'bg-red-100 text-red-600',
    new_issue: 'bg-blue-100 text-blue-600',
  }
  return (
    <div className="space-y-3">
      {data.judge_comment && (
        <SectionCard icon={MessageSquare} title="法官点评" color={{ bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', icon: 'text-slate-500' }}>
          <p className="text-xs text-slate-700 leading-relaxed">{data.judge_comment}</p>
        </SectionCard>
      )}
      {data.round_evaluation && (
        <div className="grid grid-cols-2 gap-3">
          {data.round_evaluation.plaintiff_strength && (
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3">
              <span className="text-[10px] font-medium text-emerald-600 mb-1 block">原告优势</span>
              <p className="text-[11px] text-emerald-700 leading-relaxed">{data.round_evaluation.plaintiff_strength}</p>
            </div>
          )}
          {data.round_evaluation.plaintiff_weakness && (
            <div className="rounded-lg bg-red-50 border border-red-200 p-3">
              <span className="text-[10px] font-medium text-red-500 mb-1 block">原告不足</span>
              <p className="text-[11px] text-red-600 leading-relaxed">{data.round_evaluation.plaintiff_weakness}</p>
            </div>
          )}
          {data.round_evaluation.defendant_strength && (
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3">
              <span className="text-[10px] font-medium text-emerald-600 mb-1 block">被告优势</span>
              <p className="text-[11px] text-emerald-700 leading-relaxed">{data.round_evaluation.defendant_strength}</p>
            </div>
          )}
          {data.round_evaluation.defendant_weakness && (
            <div className="rounded-lg bg-red-50 border border-red-200 p-3">
              <span className="text-[10px] font-medium text-red-500 mb-1 block">被告不足</span>
              <p className="text-[11px] text-red-600 leading-relaxed">{data.round_evaluation.defendant_weakness}</p>
            </div>
          )}
        </div>
      )}
      {data.focus_updates && data.focus_updates.length > 0 && (
        <SectionCard icon={ListChecks} title="焦点进展" color={{ bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', icon: 'text-blue-600' }}>
          <div className="space-y-1.5">
            {data.focus_updates.map((fu, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="text-[10px] font-medium text-blue-800">{fu.focus_id}</span>
                <Tag text={fu.status} colorClass={statusColor[fu.status] || 'bg-slate-100 text-slate-600'} />
                <span className="text-blue-600 flex-1">{fu.progress}</span>
              </div>
            ))}
          </div>
        </SectionCard>
      )}
      {data.facts_established && data.facts_established.length > 0 && (
        <SectionCard icon={CheckCircle} title="本轮认定事实" color={{ bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', icon: 'text-emerald-600' }}>
          <ul className="space-y-1">
            {data.facts_established.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-emerald-700">
                <CheckCircle size={11} className="text-emerald-500 mt-0.5 flex-shrink-0" />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
      {data.evidence_needed && data.evidence_gap_description && (
        <div className="rounded-xl bg-red-50 border border-red-300 p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle size={14} className="text-red-600" />
            <span className="text-xs font-semibold text-red-700">证据不足 — 需要补证</span>
          </div>
          <p className="text-xs text-red-600 leading-relaxed">{data.evidence_gap_description}</p>
        </div>
      )}
      {data.next_round_guidance && (
        <SectionCard icon={Info} title="下轮指引" color={{ bg: 'bg-indigo-50', border: 'border-indigo-200', text: 'text-indigo-700', icon: 'text-indigo-600' }}>
          <p className="text-xs text-indigo-700 leading-relaxed">{data.next_round_guidance}</p>
        </SectionCard>
      )}
    </div>
  )
}

// ============================================================
// 裁决渲染（IRAC 结构 — 原有逻辑保留）
// ============================================================

function VerdictRenderer({ verdict }: { verdict: VerdictData }) {
  return (
    <div className="space-y-4">
      {/* 争议焦点 */}
      {verdict.issue && (
        <div className="rounded-xl bg-amber-50 border border-amber-200 p-4">
          <div className="flex items-center gap-2 mb-3">
            <AlertCircle size={14} className="text-amber-600" />
            <span className="text-xs font-semibold text-amber-700">争议焦点</span>
          </div>
          <div className="text-[10px] text-amber-800 bg-amber-100 rounded-lg px-3 py-2 mb-2">
            {verdict.issue.dispute_nature}
          </div>
          <ul className="space-y-2">
            {verdict.issue.legal_questions.map((q, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-amber-700">
                <span className="w-5 h-5 rounded-full bg-amber-200 text-amber-800 flex items-center justify-center flex-shrink-0 text-[9px] font-medium">{i + 1}</span>
                <span className="leading-relaxed">{q}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 适用法条 */}
      {verdict.rule && verdict.rule.applicable_laws && verdict.rule.applicable_laws.length > 0 && (
        <div className="rounded-xl bg-blue-50 border border-blue-200 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Scale size={14} className="text-blue-600" />
            <span className="text-xs font-semibold text-blue-700">适用法条</span>
          </div>
          <div className="space-y-3">
            {verdict.rule.applicable_laws.map((law, i) => (
              <div key={i} className="bg-blue-100/50 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-medium text-blue-800">{law.law_name}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-200 text-blue-700">{law.article_number}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-600">{law.relevance}</span>
                </div>
                <p className="text-xs text-blue-700 leading-relaxed">{law.article_content}</p>
              </div>
            ))}
          </div>
          {verdict.rule.judicial_interpretations && verdict.rule.judicial_interpretations.length > 0 && (
            <div className="mt-3 pt-3 border-t border-blue-200">
              <span className="text-[10px] font-medium text-blue-600 mb-2 block">相关司法解释</span>
              <ul className="space-y-1">
                {verdict.rule.judicial_interpretations.map((item, i) => (
                  <li key={i} className="text-xs text-blue-600">{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* 事实认定 */}
      {verdict.application && verdict.application.fact_finding && verdict.application.fact_finding.length > 0 && (
        <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-4">
          <div className="flex items-center gap-2 mb-3">
            <FileText size={14} className="text-emerald-600" />
            <span className="text-xs font-semibold text-emerald-700">事实认定</span>
          </div>
          <div className="space-y-3">
            {verdict.application.fact_finding.map((fact, i) => (
              <div key={i} className="bg-emerald-100/50 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-emerald-800">事实 {i + 1}</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                    fact.certainty === '确定' ? 'bg-emerald-200 text-emerald-800' :
                    fact.certainty === '高度可能' ? 'bg-amber-100 text-amber-700' :
                    'bg-slate-200 text-slate-600'
                  }`}>{fact.certainty}</span>
                </div>
                <p className="text-xs text-emerald-700 leading-relaxed mb-1">{fact.fact}</p>
                <p className="text-[10px] text-emerald-600"><span className="font-medium">证据依据：</span>{fact.evidence_basis}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 法律分析 */}
      {verdict.application && verdict.application.legal_analysis && (
        <div className="rounded-xl bg-indigo-50 border border-indigo-200 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Info size={14} className="text-indigo-600" />
            <span className="text-xs font-semibold text-indigo-700">法律分析</span>
          </div>
          <p className="text-xs text-indigo-800 leading-relaxed whitespace-pre-wrap">{verdict.application.legal_analysis}</p>
          {verdict.application.fault_determination && (
            <div className="mt-3 pt-3 border-t border-indigo-200">
              <span className="text-[10px] font-medium text-indigo-600 mb-2 block">过错比例</span>
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <div className="flex justify-between text-[10px] mb-1">
                    <span className="text-indigo-700">原告过错</span>
                    <span className="text-indigo-600">{verdict.application.fault_determination.plaintiff_fault_ratio}%</span>
                  </div>
                  <div className="h-1.5 bg-indigo-200 rounded-full overflow-hidden">
                    <div className="h-full bg-indigo-500 rounded-full transition-all" style={{ width: `${verdict.application.fault_determination.plaintiff_fault_ratio}%` }} />
                  </div>
                </div>
                <div className="flex-1">
                  <div className="flex justify-between text-[10px] mb-1">
                    <span className="text-indigo-700">被告过错</span>
                    <span className="text-indigo-600">{verdict.application.fault_determination.defendant_fault_ratio}%</span>
                  </div>
                  <div className="h-1.5 bg-indigo-200 rounded-full overflow-hidden">
                    <div className="h-full bg-red-500 rounded-full transition-all" style={{ width: `${verdict.application.fault_determination.defendant_fault_ratio}%` }} />
                  </div>
                </div>
              </div>
              {verdict.application.fault_determination.reasoning && (
                <p className="text-[10px] text-indigo-600 mt-2">{verdict.application.fault_determination.reasoning}</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* 裁判结论 */}
      {verdict.conclusion && (
        <div className="rounded-xl bg-purple-50 border border-purple-200 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Gavel size={14} className="text-purple-600" />
            <span className="text-xs font-semibold text-purple-700">裁判结论</span>
          </div>
          <div className="bg-purple-100/50 rounded-lg p-3 mb-3">
            <p className="text-xs text-purple-800 font-medium">{verdict.conclusion.verdict}</p>
          </div>
          {verdict.conclusion.specific_orders && verdict.conclusion.specific_orders.length > 0 && (
            <div className="space-y-2">
              <span className="text-[10px] font-medium text-purple-600">判决主文</span>
              <ul className="space-y-1">
                {verdict.conclusion.specific_orders.map((order, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-purple-700">
                    <CheckCircle size={12} className="text-purple-500 mt-0.5 flex-shrink-0" />
                    <span>{order}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {verdict.conclusion.damage_calculation && (
            <div className="mt-3 pt-3 border-t border-purple-200">
              <span className="text-[10px] font-medium text-purple-600 mb-2 block">赔偿计算</span>
              <div className="flex items-center justify-between bg-purple-100/30 rounded-lg px-3 py-2">
                <span className="text-xs text-purple-700">赔偿总额</span>
                <span className="text-sm font-semibold text-purple-800">¥{verdict.conclusion.damage_calculation.total_amount.toLocaleString()}</span>
              </div>
              {verdict.conclusion.damage_calculation.breakdown && (
                <p className="text-[10px] text-purple-600 mt-1">{verdict.conclusion.damage_calculation.breakdown}</p>
              )}
            </div>
          )}
          {verdict.conclusion.litigation_costs && (
            <div className="mt-2"><span className="text-[10px] text-purple-600">诉讼费用：{verdict.conclusion.litigation_costs}</span></div>
          )}
          {verdict.conclusion.enforcement_period && (
            <div className="mt-1"><span className="text-[10px] text-purple-600">履行期限：{verdict.conclusion.enforcement_period}</span></div>
          )}
        </div>
      )}

      {/* 不同意见 */}
      {verdict.dissenting_opinion && verdict.dissenting_opinion.trim() !== '' && (
        <div className="rounded-xl bg-gray-100 border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle size={14} className="text-gray-600" />
            <span className="text-xs font-semibold text-gray-700">不同意见</span>
          </div>
          <p className="text-xs text-gray-600 leading-relaxed">{verdict.dissenting_opinion}</p>
        </div>
      )}
    </div>
  )
}

// ============================================================
// 通用 JSON 渲染（未知结构）
// ============================================================

function GenericJsonRenderer({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([, v]) => {
    if (v === null || v === undefined || v === '') return false
    if (Array.isArray(v) && v.length === 0) return false
    return true
  })
  if (entries.length === 0) return <PlainTextRenderer content={JSON.stringify(data, null, 2)} />

  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded-lg bg-slate-50 border border-slate-200 p-3">
          <span className="text-[10px] font-medium text-slate-500 mb-1 block">{key}</span>
          {Array.isArray(value) ? (
            <ul className="space-y-1">
              {(value as unknown[]).map((item, i) => (
                <li key={i} className="text-xs text-slate-600">
                  {typeof item === 'object' ? JSON.stringify(item, null, 0) : String(item)}
                </li>
              ))}
            </ul>
          ) : typeof value === 'object' ? (
            <pre className="text-[11px] text-slate-600 whitespace-pre-wrap font-mono">{JSON.stringify(value, null, 2)}</pre>
          ) : (
            <p className="text-xs text-slate-600 leading-relaxed">{String(value)}</p>
          )}
        </div>
      ))}
    </div>
  )
}

// ============================================================
// 主组件：自动检测 JSON 类型并渲染
// ============================================================

export default function JudgeVerdictCard({ content }: { content: string }) {
  // 从混合文本中提取 JSON 和前后文本
  const { beforeText, json: data, afterText } = extractJsonAndText(content)

  // 非 JSON → 纯文本渲染
  if (!data) {
    return <PlainTextRenderer content={content} />
  }

  // 判断 JSON 类型
  const renderJson = () => {
    // 裁决 JSON（IRAC 结构）
    if (data.issue || data.rule || data.application || data.conclusion) {
      return <VerdictRenderer verdict={data as unknown as VerdictData} />
    }
    // 开庭 JSON
    if (data.focus_points || data.opening_statement || data.facts_to_clarify) {
      return <OpeningRenderer data={data as unknown as OpeningData} />
    }
    // 法庭调查 JSON
    if (data.investigation_questions || data.facts_confirmed || data.facts_disputed || data.evidence_gaps) {
      return <InvestigationRenderer data={data as unknown as InvestigationData} />
    }
    // 辩论点评 JSON
    if (data.round_evaluation || data.focus_updates || data.judge_comment || data.next_round_guidance) {
      return <EvaluationRenderer data={data as unknown as EvaluationData} />
    }
    // 未知 JSON 结构 → 通用渲染
    return <GenericJsonRenderer data={data} />
  }

  return (
    <div className="space-y-3">
      {/* JSON 前的文本 */}
      {beforeText && (
        <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
          {cleanMarkdown(beforeText)}
        </div>
      )}
      {/* JSON 结构化渲染 */}
      {renderJson()}
      {/* JSON 后的文本 */}
      {afterText && (
        <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
          {cleanMarkdown(afterText)}
        </div>
      )}
    </div>
  )
}
