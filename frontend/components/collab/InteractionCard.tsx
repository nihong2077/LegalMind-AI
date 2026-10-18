'use client'

/**
 * 交互卡片（T1.8-M2 / M4）
 * - 通用卡：渲染 question，提示在下方输入框作答（作为普通消息发送）
 * - court 补证卡（card_type==='evidence_supplement'）：title + hint + question
 * - takeover 卡（type==='takeover'）：轮到你以某 Agent 身份发言 + 「交还给 AI」按钮
 * - 所有卡均提供「结束会商」（用户主权：注入 conclude 收尾，F6）
 */
import { FileText, Flag, Handshake, HelpCircle, Undo2 } from 'lucide-react'
import { InteractionPayload } from '@/store/useCollabStreamStore'

interface InteractionCardProps {
  pending: InteractionPayload
  onHandBack: () => void
  /** 用户主权：结束会商（注入 conclude 收尾） */
  onConclude?: () => void
  disabled?: boolean
}

const concludeBtnClass =
  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-medium hover:bg-slate-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0'

export default function InteractionCard({
  pending,
  onHandBack,
  onConclude,
  disabled,
}: InteractionCardProps) {
  const isTakeover = pending.type === 'takeover'
  const isEvidence = pending.card_type === 'evidence_supplement'

  return (
    <div className="mx-4 my-2 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <div className="flex items-center gap-2">
        {isTakeover ? (
          <Handshake size={15} className="text-blue-600 flex-shrink-0" />
        ) : isEvidence ? (
          <FileText size={15} className="text-blue-600 flex-shrink-0" />
        ) : (
          <HelpCircle size={15} className="text-blue-600 flex-shrink-0" />
        )}
        <h4 className="text-sm font-semibold text-slate-800">
          {isTakeover
            ? `轮到你以「${pending.agent_name || '该角色'}」身份发言`
            : pending.title || '需要你的参与'}
        </h4>
      </div>

      {pending.hint && <p className="mt-2 text-xs text-slate-500 leading-relaxed">{pending.hint}</p>}

      {pending.question && (
        <p className="mt-2 text-sm text-slate-700 leading-relaxed">{pending.question}</p>
      )}

      {isTakeover ? (
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-[11px] text-slate-400">可在下方输入框直接发言，或交还给 AI 代答</p>
          <div className="flex items-center gap-2 flex-shrink-0">
            {onConclude && (
              <button onClick={onConclude} disabled={disabled} className={concludeBtnClass}>
                <Flag size={13} />
                结束会商
              </button>
            )}
            <button
              onClick={onHandBack}
              disabled={disabled}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-blue-600 text-blue-600 text-xs font-medium hover:bg-blue-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Undo2 size={13} />
              交还给 AI
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-[11px] text-slate-400">请在下方输入框作答（作为普通消息发送）。</p>
          {onConclude && (
            <button onClick={onConclude} disabled={disabled} className={concludeBtnClass}>
              <Flag size={13} />
              结束会商
            </button>
          )}
        </div>
      )}
    </div>
  )
}
