'use client'

/**
 * 消息气泡（T1.8-M2 / M4）
 * - minutes：会商纪要卡（书记员产出）
 * - card：会商卡片（结构化产出）
 * - user：右对齐（复用 chat-bubble-user 令牌）
 * - agent/tool：左对齐 + Avatar + 名字
 * - notice（speaker_notice）：轮次分隔条，无背景、小字居中（隐藏主持人身份）
 * - system/notice：居中弱化（成员变动等通知）
 */
import { ClipboardList, FileText } from 'lucide-react'
import Avatar from './Avatar'

interface MessageBubbleProps {
  senderType: string
  senderName: string
  content: string
  msgType?: string
  avatar?: string | null
  seed?: string
  /** 消息元数据（引用卡携带 card_type / citations） */
  metadata?: Record<string, unknown> | null
  /** 流式生成中：追加闪烁光标 */
  streaming?: boolean
}

export default function MessageBubble({
  senderType,
  senderName,
  content,
  msgType = 'text',
  avatar,
  seed,
  metadata,
  streaming = false,
}: MessageBubbleProps) {
  if (msgType === 'minutes' || msgType === 'card') {
    const isMinutes = msgType === 'minutes'
    const cardType = typeof metadata?.card_type === 'string' ? metadata.card_type : ''
    const citations = Array.isArray(metadata?.citations)
      ? (metadata?.citations as {
          source?: string
          title?: string
          url?: string
          content?: string
          score?: number
        }[])
      : []
    const title = isMinutes
      ? '会商纪要'
      : cardType === 'case_citation'
        ? '类案引用'
        : cardType === 'law_citation'
          ? '法规引用'
          : cardType === 'web_citation'
            ? '联网检索'
            : cardType === 'memory_citation'
              ? '记忆引用'
              : cardType === 'message_citation'
                ? '会话引用'
                : '会商卡片'
    return (
      <div className="my-2 rounded-xl border border-blue-200 bg-white overflow-hidden">
        <div className="px-3 py-2 bg-blue-50 flex items-center gap-2">
          {isMinutes ? (
            <ClipboardList size={14} className="text-blue-600 flex-shrink-0" />
          ) : (
            <FileText size={14} className="text-blue-600 flex-shrink-0" />
          )}
          <span className="text-xs font-semibold text-blue-700">{title}</span>
          {senderName && <span className="text-[11px] text-slate-400">· {senderName}</span>}
        </div>
        {citations.length > 0 ? (
          <div className="px-3 py-1 divide-y divide-slate-100">
            {citations.map((c, i) => (
              <div key={i} className="py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-medium text-blue-700 truncate">
                    {c.title || c.source || '系统'}
                  </span>
                  {typeof c.score === 'number' && (
                    <span className="text-[10px] text-slate-400 flex-shrink-0">
                      {c.score.toFixed(2)}
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-600 mt-0.5 leading-relaxed whitespace-pre-wrap break-words">
                  {c.content}
                </p>
                {c.url && (
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] text-blue-500 hover:underline break-all"
                  >
                    {c.url}
                  </a>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="px-3 py-3">
            <p className="text-sm text-slate-700 whitespace-pre-wrap break-words leading-relaxed">
              {content}
            </p>
          </div>
        )}
      </div>
    )
  }

  // 轮次发言分隔条：无背景、小字居中（隐藏主持人身份的中性提示）
  if (msgType === 'notice' && metadata?.kind === 'speaker_notice') {
    return (
      <div className="flex justify-center my-2">
        <span className="text-[11px] text-slate-400">{content}</span>
      </div>
    )
  }

  if (senderType === 'system') {
    return (
      <div className="flex justify-center my-2">
        <span className="px-3 py-1 rounded-full bg-slate-100 text-[11px] text-slate-400">
          {content}
        </span>
      </div>
    )
  }

  if (senderType === 'user') {
    return (
      <div className="flex flex-col items-end">
        <div className="chat-bubble-user text-sm whitespace-pre-wrap break-words">
          {content || '…'}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-2 max-w-[85%]">
      <Avatar name={senderName} avatar={avatar} seed={seed || senderName} size={32} />
      <div className="flex flex-col gap-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-slate-400 truncate">
            {senderName || '智能体'}
          </span>
        </div>
        <div className="chat-bubble-assistant text-sm whitespace-pre-wrap break-words">
          {content}
          {streaming && (
            <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-slate-400 align-middle rounded-sm animate-pulse" />
          )}
        </div>
      </div>
    </div>
  )
}
