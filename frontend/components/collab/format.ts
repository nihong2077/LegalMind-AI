import { AgentInfo, Conversation } from '@/app/lib/collab'

/** 会话展示标题：direct 无 title 时回退到目标 Agent 名称，最后兜底为「新会话」 */
export function conversationTitle(conv: Conversation, agents: AgentInfo[]): string {
  if (conv.title) return conv.title
  if (conv.type === 'direct' && conv.target_agent_id) {
    const agent = agents.find((a) => a.agent_id === conv.target_agent_id)
    return agent?.name || conv.target_agent_id
  }
  if (conv.case_type) return conv.case_type
  return '新会话'
}

/** 相对时间：刚刚 / N 分钟前 / N 小时前 / 昨天 / N 天前 / M-D */
export function relativeTime(iso?: string | null): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hour = Math.floor(min / 60)
  if (hour < 24) return `${hour} 小时前`
  const day = Math.floor(hour / 24)
  if (day === 1) return '昨天'
  if (day < 7) return `${day} 天前`
  const d = new Date(t)
  return `${d.getMonth() + 1}-${d.getDate()}`
}
