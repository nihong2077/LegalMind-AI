'use client'

import { useState } from 'react'
import {
  ChevronRight, Star, Lightbulb, AlertTriangle,
  BookOpen, HelpCircle, Shield, Zap, FileText
} from 'lucide-react'
import { useChatStore } from '@/store/useChatStore'

const SCENARIOS = [
  { icon: '🏠', label: '房屋纠纷', desc: '押金 / 维修 / 提前解约 / 租赁合同', keywords: ['租赁', '押金', '租房'] },
  { icon: '💼', label: '借贷纠纷', desc: '借款 / 利息 / 担保 / 借贷合同', keywords: ['借贷', '借款', '利息', '欠款'] },
  { icon: '📝', label: '劳动纠纷', desc: '辞退 / 加班 / 社保 / 劳动合同', keywords: ['劳动', '加班', '辞退', '社保'] },
  { icon: '⚖️', label: '劳动争议', desc: '加班费 / 辞退赔偿 / 工伤认定', keywords: ['争议', '工伤', '仲裁'] },
]

const RECOMMENDED_STEPS: Record<string, string[]> = {
  '租赁': ['先与房东协商或发送律师函', '收集租赁合同、押金收据、聊天记录等证据', '向法院提起诉讼或申请仲裁'],
  '借贷': ['先与对方协商并保留沟通记录', '收集借条、转账记录、聊天证据', '向法院提起民事诉讼'],
  '劳动': ['先与用人单位协商或向劳动监察部门投诉', '收集劳动合同、工资条、考勤记录', '申请劳动仲裁（前置程序）'],
  '消费': ['先与商家协商或向平台投诉', '保留购物凭证、商品照片、聊天记录', '向消协投诉或法院起诉'],
}

interface RightPanelProps {
  onQuickQuestionClick?: (question: string) => void
}

export default function RightPanel({ onQuickQuestionClick }: RightPanelProps) {
  const [activeSection, setActiveSection] = useState<string | null>(null)
  const { rightPanelData } = useChatStore()
  const { quickQuestions, relatedLaws, riskWarnings, termExplanations, scenarioType } = rightPanelData

  const steps = RECOMMENDED_STEPS[scenarioType || ''] || RECOMMENDED_STEPS['租赁']

  return (
    <aside className="w-72 border-l border-white/5 flex-shrink-0 overflow-y-auto bg-[#0c1729]/40">
      <div className="p-4 space-y-4">
        {/* 快捷问题 */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Zap size={13} className="text-blue-400" />
              <span className="text-xs font-semibold text-gold-200/80">快捷问题</span>
            </div>
            <button onClick={() => setActiveSection(activeSection === 'quick' ? null : 'quick')}
              className={`text-[10px] text-blue-400 hover:text-blue-300 transition-colors`}>
              {activeSection === 'quick' ? '收起' : '展开'}
            </button>
          </div>
          {(activeSection === 'quick' || !activeSection) && (
            <div className="flex flex-wrap gap-1.5">
              {['律法不退', '借款纠纷', '劳动合同', '合规咨询'].map((q, i) => (
                <button key={i} onClick={() => onQuickQuestionClick?.(q)}
                  className="px-2.5 py-1 rounded-full border border-white/10 text-[10px] text-gold-200/55 hover:text-blue-400 hover:border-blue-400/25 hover:bg-blue-500/[0.04] transition-all">
                  {q}
                </button>
              ))}
            </div>
          )}
        </section>

        {/* 常见场景 */}
        <section className="pt-3 border-t border-white/5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Lightbulb size={13} className="text-emerald-400" />
              <span className="text-xs font-semibold text-gold-200/80">常见场景</span>
            </div>
            <button className="flex items-center gap-0.5 text-[10px] text-blue-400 hover:text-blue-300">
              更多 <ChevronRight size={10} />
            </button>
          </div>
          <div className="space-y-1.5">
            {SCENARIOS.map((s, i) => (
              <button key={i} onClick={() => onQuickQuestionClick?.(s.desc)}
                className={`w-full flex items-center gap-2.5 p-2 rounded-lg text-left group transition-all ${
                  scenarioType && s.keywords.includes(scenarioType)
                    ? 'bg-emerald-500/[0.06] border border-emerald-400/15'
                    : 'hover:bg-white/[0.02]'
                }`}>
                <span className="text-base">{s.icon}</span>
                <div className="min-w-0 flex-1">
                  <p className={`text-[11px] font-medium truncate ${scenarioType && s.keywords.includes(scenarioType) ? 'text-emerald-350' : 'text-gold-200/65 group-hover:text-gold-200'}`}>
                    {s.label}
                  </p>
                  <p className="text-[9px] text-gold-200/30 truncate">{s.desc}</p>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* 推荐步骤 */}
        <section className="pt-3 border-t border-white/5">
          <div className="flex items-center gap-2 mb-3">
            <Star size={13} className="text-orange-400" />
            <span className="text-xs font-semibold text-gold-200/80">推荐下一步</span>
          </div>
          <div className="space-y-1.5">
            {steps.map((step, i) => (
              <button key={i} onClick={() => onQuickQuestionClick?.(step)}
                className="w-full flex items-start gap-2 p-2 rounded-lg hover:bg-white/[0.02] text-left group transition-all">
                <span className="w-4 h-4 rounded-full bg-orange-500/10 text-orange-400 text-[9px] flex items-center justify-center flex-shrink-0 mt-0.5">{i + 1}</span>
                <span className="text-[10px] text-gold-200/50 leading-relaxed group-hover:text-gold-200/75 line-clamp-2 flex-1">{step}</span>
                <ChevronRight size={10} className="text-gold-200/20 mt-0.5 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            ))}
          </div>
        </section>

        {/* 风险提示 */}
        {(riskWarnings.length > 0 || true) && (
          <section className="pt-3 border-t border-white/5">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle size={13} className="text-red-400" />
              <span className="text-xs font-semibold text-gold-200/80">风险提示</span>
            </div>
            {riskWarnings.length > 0 ? riskWarnings.map((risk, i) => (
              <div key={i} className="rounded-lg bg-red-500/[0.04] border border-red-400/10 p-2.5">
                <p className="text-[10px] text-red-300/70 leading-relaxed">{risk}</p>
              </div>
            )) : (
              <div className="rounded-lg bg-red-500/[0.03] border border-red-400/8 p-2.5">
                <p className="text-[10px] text-gold-200/35 leading-relaxed">⚠️ 法院时效一般为3年，自权利人知道或应当知道权利被侵害时起算。请及时主张权利，避免超过诉讼时效。</p>
              </div>
            )}
          </section>
        )}

        {/* 相关法条 */}
        <section className="pt-3 border-t border-white/5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <BookOpen size={13} className="text-purple-400" />
              <span className="text-xs font-semibold text-gold-200/80">相关法条</span>
            </div>
            <button className="flex items-center gap-0.5 text-[10px] text-blue-400 hover:text-blue-300">
              更多 <ChevronRight size={10} />
            </button>
          </div>
          {relatedLaws.length > 0 ? relatedLaws.map((law, i) => (
            <div key={i} className="rounded-lg bg-purple-500/[0.03] border border-purple-400/8 p-2.5">
              <p className="text-[10px] text-gold-200/60 leading-relaxed">{law}</p>
            </div>
          )) : (
            <div className="space-y-1.5">
              {[
                '《中华人民共和国民法典》第七百零三条',
                '《中华人民共和国民法典》第五百七十九条',
                '《中华人民共和国民法典》第五百八十条',
              ].map((law, i) => (
                <div key={i} className="rounded-lg bg-purple-500/[0.02] border border-purple-400/6 p-2">
                  <p className="text-[10px] text-gold-200/45 truncate">{law}</p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 法律术语解释 */}
        <section className="pt-3 border-t border-white/5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <HelpCircle size={13} className="text-cyan-400" />
              <span className="text-xs font-semibold text-gold-200/80">法律术语解释</span>
            </div>
            <button className="flex items-center gap-0.5 text-[10px] text-blue-400 hover:text-blue-300">
              更多 <ChevronRight size={10} />
            </button>
          </div>
          {termExplanations.length > 0 ? termExplanations.map((t, i) => (
            <div key={i} className="rounded-lg bg-cyan-500/[0.03] border border-cyan-400/8 p-2.5">
              <p className="text-[10px] font-medium text-cyan-350 mb-0.5">{t.term}</p>
              <p className="text-[10px] text-gold-200/45 leading-relaxed">{t.explanation}</p>
            </div>
          )) : (
            <div className="rounded-lg bg-cyan-500/[0.02] border border-cyan-400/6 p-2.5">
              <p className="text-[10px] text-gold-200/40 leading-relaxed">在民事法律过程中，因各种老化或疏忽导致使用过期的证据。</p>
            </div>
          )}
        </section>

        {/* 合规指南 */}
        <section className="pt-3 border-t border-white/5">
          <div className="flex items-center gap-2 mb-3">
            <Shield size={13} className="text-green-400" />
            <span className="text-xs font-semibold text-gold-200/80">合规指南</span>
          </div>
          <div className="rounded-lg bg-green-500/[0.03] border border-green-400/10 p-2.5">
            <p className="text-[10px] text-gold-200/40 leading-relaxed">在民事法律过程中，因各种老化或疏忽导致使用过期的证据。</p>
          </div>
        </section>
      </div>

      {/* 收起按钮 */}
      <div className="sticky bottom-0 pt-3 pb-4 px-4 border-t border-white/5 bg-[#0c1729]/95 backdrop-blur-sm">
        <button onClick={() => setActiveSection(null)}
          className="w-full flex items-center justify-center gap-1 text-[10px] text-gold-200/35 hover:text-gold-200/60 transition-colors py-1">
          收起 <svg xmlns="http://www.w3.org/2000/svg" width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="18 15 12 9 6 15"/></svg>
        </button>
      </div>
    </aside>
  )
}
