/**
 * 案情搜索前端数据层（T3.2）
 *
 * 对齐后端：
 * - `POST /api/search/unified`（routers/search.py）：四路并行召回 + 分组返回
 * - `POST /api/conversations/{id}/forward`（routers/conversations.py）：把结果作为
 *   「上下文卡片」转发进会话，**不触发轮次**。
 * 统一走 `request` 解包信封，失败抛 ApiError。
 */
import { request } from './http'
import { memoryTypeLabel } from './memory'

export type SearchSource = 'law' | 'judge' | 'memory' | 'messages'
/** 前端 Tab：'all' = 不过滤（后端一次返回四路，前端按 Tab 切） */
export type SearchTab = 'all' | SearchSource

/** 法规 / 类案结果（law / judge 同形状） */
export interface KnowledgeResult {
  type: 'law' | 'judge'
  content: string
  source: string
  score: number
  domain: string
  doc_type: string
}

export interface MemoryResult {
  type: 'memory'
  id: string
  memory_type: string
  content: string
  summary: string | null
  importance: number | null
  case_id: string | null
  score: number
  created_at: string | null
}

export interface MessageResult {
  type: 'messages'
  id: string
  conversation_id: string
  conversation_title: string | null
  sender_type: string
  sender_name: string | null
  content: string
  round: number
  created_at: string | null
}

export type SearchResult = KnowledgeResult | MemoryResult | MessageResult

export interface SearchCounts {
  law: number
  judge: number
  memory: number
  messages: number
  total: number
}

export interface UnifiedSearchResponse {
  query: string
  results: {
    law: KnowledgeResult[]
    judge: KnowledgeResult[]
    memory: MemoryResult[]
    messages: MessageResult[]
  }
  counts: SearchCounts
  /** 单路失败被隔离时：{ source: 错误信息 } */
  errors: Record<string, string>
  took_ms: number
}

export interface UnifiedSearchParams {
  query: string
  top_k?: number
  message_limit?: number
  use_hyde?: boolean
  case_id?: string
  sources?: SearchSource[]
}

/** 单个 Tab 的中文标签与顺序 */
export const SEARCH_TABS: { key: SearchTab; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'law', label: '法规' },
  { key: 'judge', label: '类案' },
  { key: 'memory', label: '我的记忆' },
  { key: 'messages', label: '会话记录' },
]

export async function unifiedSearch(
  params: UnifiedSearchParams,
): Promise<UnifiedSearchResponse> {
  return request<UnifiedSearchResponse>('/api/search/unified', {
    method: 'POST',
    body: params,
  })
}

// ---------------- 转发（上下文卡片） ----------------

/** 引用卡形状，对齐 MessageBubble 的 metadata.citations 渲染 */
export interface ForwardCitation {
  source?: string
  title?: string
  url?: string
  content?: string
  score?: number
}

export interface ForwardCardBody {
  card_type?: string
  citations?: ForwardCitation[]
  content?: string
}

export interface ForwardResult {
  message: Record<string, unknown>
  event_id: string
  turn_id: string | null
  status: string
}

/** 转发到指定会话（仅落库 + SSE，不触发轮次） */
export async function forwardToConversation(
  conversationId: string,
  body: ForwardCardBody,
): Promise<ForwardResult> {
  return request<ForwardResult>(`/api/conversations/${conversationId}/forward`, {
    method: 'POST',
    body,
  })
}

// ---------------- 结果 → 展示 / 引用卡 ----------------

/** 列表项标题（法规名 / 类案名 / 记忆类型 / 会话标题） */
export function resultTitle(r: SearchResult): string {
  switch (r.type) {
    case 'law':
    case 'judge':
      return r.source || (r.type === 'law' ? '法规' : '类案')
    case 'memory':
      return memoryTypeLabel(r.memory_type)
    case 'messages':
      return r.conversation_title || '会话记录'
  }
}

/** 列表项正文 */
export function resultBody(r: SearchResult): string {
  if (r.type === 'memory') return r.summary || r.content
  return r.content
}

/** 结果所属 source 分类（供 Tab 归属判断） */
export function resultSource(r: SearchResult): SearchSource {
  return r.type
}

/** 归一化为转发用引用卡 */
export function resultToCitation(r: SearchResult): ForwardCitation {
  if (r.type === 'law' || r.type === 'judge') {
    return { source: r.type === 'law' ? '法规' : '类案', title: r.source, content: r.content, score: r.score }
  }
  if (r.type === 'memory') {
    return { source: memoryTypeLabel(r.memory_type), title: r.summary || r.content, content: r.content, score: r.score }
  }
  return { source: r.sender_name || '会话', title: r.conversation_title || '会话记录', content: r.content }
}

/** 落库正文（进入共享上下文窗，供 Agent 引用）：`【标题】正文` */
export function resultToForwardText(r: SearchResult): string {
  const title = resultTitle(r)
  const body = resultBody(r)
  return title && body ? `【${title}】${body}` : body || title
}

/** 卡片类型（映射到 MessageBubble 的 card_type 标题） */
export function resultCardType(r: SearchResult): string {
  if (r.type === 'law') return 'law_citation'
  if (r.type === 'judge') return 'case_citation'
  if (r.type === 'memory') return 'memory_citation'
  return 'message_citation'
}
