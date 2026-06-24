import { AlertTriangle } from 'lucide-react'

/**
 * 免责声明组件
 * 说明：AI 回答可能出错，仅供参考，不构成司法建议
 *
 * variant:
 * - "compact": 紧凑模式（单行），适合输入框下方、顶部栏
 * - "full": 完整模式（多行），适合页面底部、报告末尾
 */
export default function Disclaimer({ variant = 'compact' }: { variant?: 'compact' | 'full' }) {
  if (variant === 'full') {
    return (
      <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3">
        <div className="flex items-start gap-2">
          <AlertTriangle size={14} className="text-amber-500 mt-0.5 flex-shrink-0" />
          <div className="space-y-1">
            <p className="text-xs font-medium text-amber-700">免责声明</p>
            <p className="text-[11px] text-amber-600 leading-relaxed">
              本平台由人工智能技术提供，回答可能存在错误或偏差，仅供参考，<strong>不构成任何司法建议或法律意见</strong>。
              法律问题具有高度专业性，如遇实际法律纠纷，请务必咨询执业律师或相关法律专业人士。
            </p>
          </div>
        </div>
      </div>
    )
  }

  // 紧凑模式
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <AlertTriangle size={12} className="flex-shrink-0" />
      <span>AI 回答可能出错，仅供参考，不构成司法建议。遇法律问题请咨询专业律师。</span>
    </div>
  )
}
