import { FileText, Scale, Gavel, CheckCircle, AlertCircle, Info } from 'lucide-react'

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

interface JudgeVerdict {
  issue?: {
    legal_questions: string[]
    dispute_nature: string
  }
  rule?: {
    applicable_laws: ApplicableLaw[]
    judicial_interpretations: string[]
  }
  application?: {
    fact_finding: FactFinding[]
    legal_analysis: string
    fault_determination: {
      plaintiff_fault_ratio: number
      defendant_fault_ratio: number
      reasoning: string
    }
  }
  conclusion?: {
    verdict: string
    specific_orders: string[]
    damage_calculation?: {
      total_amount: number
      breakdown: string
    }
    litigation_costs: string
    enforcement_period: string
  }
  dissenting_opinion?: string
}

export default function JudgeVerdictCard({ content }: { content: string }) {
  let verdict: JudgeVerdict | null = null
  
  try {
    verdict = JSON.parse(content)
  } catch {
    return (
      <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
        {content}
      </div>
    )
  }

  if (!verdict || (!verdict.issue && !verdict.rule && !verdict.application && !verdict.conclusion)) {
    return (
      <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
        {content}
      </div>
    )
  }

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
      {verdict.rule && verdict.rule.applicable_laws.length > 0 && (
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
      {verdict.application && verdict.application.fact_finding.length > 0 && (
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
                  }`}>
                    {fact.certainty}
                  </span>
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
          
          {/* 过错比例 */}
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
            <div className="mt-2">
              <span className="text-[10px] text-purple-600">诉讼费用：{verdict.conclusion.litigation_costs}</span>
            </div>
          )}
          {verdict.conclusion.enforcement_period && (
            <div className="mt-1">
              <span className="text-[10px] text-purple-600">履行期限：{verdict.conclusion.enforcement_period}</span>
            </div>
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