import {
  API_BASE,
  ApiError,
  request,
  requestRaw,
  getToken,
  setToken,
  setUsername,
  clearToken,
  isAuthenticated,
  getUsername,
} from './http'

// 凭证相关统一由 http.ts 管理，此处继续对页面导出原符号
export { setToken, clearToken, isAuthenticated, getUsername }
export { ApiError } from './http'

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  username?: string
}

export interface StreamChunk {
  content: string
  role: string
}

export interface StreamDone {
  content: string
  role: string
  finish_reason: string
}

/** SSE error 事件统一形状（T0.12）；error 为兼容字段，新逻辑读 message */
export interface StreamError {
  code?: number
  message: string
  error: string
  detail?: string
  retryable?: boolean
  request_id?: string
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  const data = await request<TokenResponse>(`/api/auth/token`, {
    method: 'POST',
    body: { username, password },
  })
  // 先落用户名（Token 键按用户名隔离，需先确定身份），再写隔离 Token
  const who = data.username || username
  setUsername(who)
  setToken(data.access_token, who)
  return data
}

export async function register(username: string, password: string): Promise<TokenResponse> {
  const data = await request<TokenResponse>(`/api/auth/register`, {
    method: 'POST',
    body: { username, password },
  })
  const who = data.username || username
  setUsername(who)
  setToken(data.access_token, who)
  return data
}

export async function chatCompletion(messages: ChatMessage[], model = 'deepseek-flash') {
  const token = getToken()
  if (!token) throw new Error('未登录')
  return request(`${API_BASE}/api/chat`, {
    method: 'POST',
    body: { messages, model },
  })
}

/** 通用 SSE 流解析器，供 chatStream / debateStream / contractReviewStream 复用 */
async function* parseSSEStream<T>(
  res: Response,
  eventMap: Record<string, (parsed: unknown) => T>,
): AsyncGenerator<T> {
  const reader = res.body?.getReader()
  if (!reader) throw new Error('无法获取响应流')

  const decoder = new TextDecoder()
  // 按 SSE 事件块（空行分隔）解析：event:/data: 可能跨 TCP 分片到达，
  // 必须在 chunk 之间保留事件名与数据缓冲。
  let buffer = ''

  function* dispatchBlock(rawBlock: string): Generator<T> {
    let eventName = ''
    const dataLines: string[] = []
    for (const line of rawBlock.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).replace(/^ /, ''))
      }
    }
    if (!dataLines.length) return
    try {
      const parsed = JSON.parse(dataLines.join('\n'))
      const mapper = eventMap[eventName]
      if (mapper) yield mapper(parsed)
    } catch {
      // 忽略非 JSON 数据（如 ping/注释）
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let sep: number
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        yield* dispatchBlock(block)
      }
    }
    // 连接结束时刷新无空行结尾的末块
    if (buffer.trim()) {
      yield* dispatchBlock(buffer)
    }
  } finally {
    reader.releaseLock()
  }
}

type ChatStreamEvent =
  | { type: 'chunk'; data: StreamChunk }
  | { type: 'done'; data: StreamDone }
  | { type: 'error'; data: StreamError }
  | { type: 'status'; data: { phase: string; message: string } }

export async function* chatStream(
  messages: ChatMessage[],
  model = 'deepseek-flash',
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const res = await requestRaw(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    body: { messages, model },
    signal,
  })

  yield* parseSSEStream<ChatStreamEvent>(res, {
    message: (p) => ({ type: 'chunk', data: p as StreamChunk }),
    done: (p) => ({ type: 'done', data: p as StreamDone }),
    error: (p) => ({ type: 'error', data: p as StreamError }),
    status: (p) => ({ type: 'status', data: p as { phase: string; message: string } }),
  })
}

export async function checkHealth(): Promise<{ status: string; redis?: unknown; litellm?: unknown }> {
  // /health 不穿信封（仅 /api/* 切换）
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) throw new Error('健康检查失败')
  return res.json()
}

export interface ModelOption {
  id: string
  name: string
  available: boolean
  status?: string
  error?: string
}

export async function listModels(): Promise<ModelOption[]> {
  const data = await request<{ models: ModelOption[] }>(`${API_BASE}/api/models`)
  return data.models || []
}

export interface DashboardStats {
  chat_count: number
  doc_count: number
  knowledge_count: number
  efficiency_gain: string
}

export interface CaseItem {
  id: string
  title: string
  description?: string
  status: string
  created_at: string
}

export interface DocumentItem {
  id: string
  name: string
  size: string
  type: string
  status: string
  uploaded_at: string
}

export async function getDashboardStats(): Promise<DashboardStats> {
  return request<DashboardStats>(`${API_BASE}/api/dashboard/stats`)
}

export async function incrementStat(key: 'chat_count' | 'doc_count'): Promise<void> {
  await request(`${API_BASE}/api/dashboard/stats/increment?key=${key}`, { method: 'POST' })
}

export async function getRecentCases(): Promise<CaseItem[]> {
  return request<CaseItem[]>(`${API_BASE}/api/dashboard/cases`)
}

export async function createCase(title: string, description = ''): Promise<CaseItem> {
  return request<CaseItem>(
    `${API_BASE}/api/dashboard/cases?title=${encodeURIComponent(title)}&description=${encodeURIComponent(description)}`,
    { method: 'POST' },
  )
}

export async function uploadDocument(file: File): Promise<DocumentItem> {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const formData = new FormData()
  formData.append('file', file)

  return request<DocumentItem>(`${API_BASE}/api/documents/upload`, {
    method: 'POST',
    body: formData,
  })
}

export async function listDocuments(): Promise<DocumentItem[]> {
  return request<DocumentItem[]>(`${API_BASE}/api/documents`)
}

export async function getDocumentContent(docId: string): Promise<string> {
  const data = await request<{ content?: string; text?: string }>(
    `${API_BASE}/api/documents/${docId}/content`,
  )
  return data.content || data.text || ''
}

export async function analyzeDocument(docId: string): Promise<{ task_id: string; doc_id: string; status: string }> {
  return request(`${API_BASE}/api/documents/${docId}/analyze`, { method: 'POST' })
}

export interface KnowledgeSearchResult {
  content: string
  source: string
  score: number
  domain: string
  doc_type: string
}

export interface KnowledgeSearchResponse {
  results: KnowledgeSearchResult[]
  total: number
}

export async function searchKnowledge(query: string, domain = 'law', topK = 8): Promise<KnowledgeSearchResponse> {
  return request<KnowledgeSearchResponse>(`${API_BASE}/api/knowledge/search`, {
    method: 'POST',
    body: { query, domain, top_k: topK, use_hyde: true },
  })
}

export interface KnowledgeListItem {
  [key: string]: string | number
}

export interface KnowledgeListResponse {
  items: KnowledgeListItem[]
  total: number
  page: number
  page_size: number
}

export async function listKnowledge(
  domain = 'law',
  category = '',
  keyword = '',
  page = 1,
  pageSize = 20,
): Promise<KnowledgeListResponse> {
  const params = new URLSearchParams({ domain, page: String(page), page_size: String(pageSize) })
  if (category) params.set('category', category)
  if (keyword) params.set('keyword', keyword)
  return request<KnowledgeListResponse>(`${API_BASE}/api/knowledge/list?${params}`)
}

export interface DebateRequest {
  case_description: string
  evidence_summary?: string
  task_type?: string
  // 是否为补证后重新启动（补证后跳过开庭阶段，直接进入辩论，且不再触发中断）
  evidence_supplemented?: boolean
}

export interface DebateResult {
  result: string
  verdict: string
  judgment_report: string
  plain_language: string
  convergence_reason: string
  kfe: Record<string, unknown>
  evidence_sufficient: boolean
  interrupt_reason: string
}

export async function runDebate(body: DebateRequest): Promise<DebateResult> {
  return request<DebateResult>(`${API_BASE}/api/debate/run`, {
    method: 'POST',
    body,
  })
}

export interface DebateStreamChunk {
  node: string
  content: string
}

export interface DebateStreamDone {
  status: string
  final_result: string
  verdict: string
  judgment_report: string
  plain_language: string
  convergence_reason: string
  kfe: Record<string, unknown>
  evidence_sufficient: boolean
  evidence_needed?: boolean
  interrupt_reason: string
  structured_summary: StructuredSummary
}

export interface StructuredSummary {
  case_type?: string
  focus_points?: string[]
  kfe_items?: Array<{ label: string; value: string; status: 'verified' | 'unverified' | 'pending' }>
  evidence_analysis?: Array<{ name: string; type: string; relevance: string; conclusion: string }>
  law_articles?: Array<{ title: string; source: string; excerpt: string; relevance: string }>
  report_sections?: {
    case_analysis?: string[]
    fact_finding?: string[]
    legal_application?: string[]
    conclusion?: string[]
  }
  mediation_suggestion?: { draft: string; enforcement: string }
  confidence_score?: number
  can_sign?: string
}

export interface DebateMetadata {
  type: string
  node: string
  kfe?: Record<string, unknown> | null
  legal_knowledge?: string | null
}

type DebateStreamEvent =
  | { type: 'chunk'; data: DebateStreamChunk }
  | { type: 'done'; data: DebateStreamDone }
  | { type: 'error'; data: StreamError }
  | { type: 'metadata'; data: DebateMetadata }

export async function* debateStream(
  body: DebateRequest,
  signal?: AbortSignal,
): AsyncGenerator<DebateStreamEvent> {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const res = await requestRaw(`${API_BASE}/api/debate/stream`, {
    method: 'POST',
    body,
    signal,
  })

  yield* parseSSEStream<DebateStreamEvent>(res, {
    message: (p) => ({ type: 'chunk', data: p as DebateStreamChunk }),
    done: (p) => ({ type: 'done', data: p as DebateStreamDone }),
    error: (p) => ({ type: 'error', data: p as StreamError }),
    metadata: (p) => ({ type: 'metadata', data: p as DebateMetadata }),
  })
}

export interface ContractReviewRequest {
  contract_text: string
  user_position?: string
  review_stance?: string
}

export interface ContractReviewResult {
  summary: Record<string, unknown>
  report: string
  classification: Record<string, unknown>
  risks: Record<string, unknown>
}

export async function reviewContract(body: ContractReviewRequest): Promise<ContractReviewResult> {
  return request<ContractReviewResult>(`${API_BASE}/api/contract/review`, {
    method: 'POST',
    body,
  })
}

export interface ContractReviewDone {
  status: string
  summary: Record<string, unknown>
  report: string
  structured_review: StructuredReviewData
}

export interface StructuredReviewData {
  case_name?: string
  risk_level_label?: string
  version?: string
  review_time?: string
  clause_tree?: Array<{ id: string; label: string; status: 'pass' | 'warning' | 'danger' | 'info'; risk_count: number }>
  clauses_display?: Array<{
    title: string; content: string; status: string;
    tags?: string[]; suggestion?: string; location?: string
  }>
  risk_list?: Array<{
    level: string; title: string; description: string;
    location?: string; legal_basis?: string; suggestion?: string
  }>
  revision_list?: Array<{
    level: string; title: string; description: string;
    original_text?: string; suggested_text?: string; location?: string
  }>
  conclusion?: {
    overall_assessment?: string; key_findings?: string[]
    must_fix_before_sign?: string[]; negotiation_priority?: string[]
  }
  report_sections?: {
    summary?: string[]; clause_details?: string[]
    risk_summary?: string[]; revision_summary?: string[]; conclusion?: string[]
  }
  stats?: {
    total_clauses: number; high_risk: number; medium_risk: number;
    low_risk: number; passed: number; completion_rate: number
  }
  can_sign?: string
}

export interface ContractReviewMetadata {
  type: 'classify' | 'risks'
  clauses?: Array<{ index: number; title: string; content: string }>
  contract_type?: string
  readability?: { readability_score: number; vague_count: number }
  meso_issues?: Record<string, unknown>[]
  micro_issues?: Record<string, unknown>[]
  loopholes?: Record<string, unknown>[]
  missing_clauses?: string[]
}

type ContractReviewStreamEvent =
  | { type: 'chunk'; data: { node: string; content: string } }
  | { type: 'done'; data: ContractReviewDone }
  | { type: 'error'; data: StreamError }
  | { type: 'metadata'; data: ContractReviewMetadata }

export async function* contractReviewStream(
  body: ContractReviewRequest,
  signal?: AbortSignal,
): AsyncGenerator<ContractReviewStreamEvent> {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const res = await requestRaw(`${API_BASE}/api/contract/review/stream`, {
    method: 'POST',
    body,
    signal,
  })

  yield* parseSSEStream<ContractReviewStreamEvent>(res, {
    message: (p) => ({ type: 'chunk', data: p as { node: string; content: string } }),
    done: (p) => ({ type: 'done', data: p as ContractReviewDone }),
    error: (p) => ({ type: 'error', data: p as StreamError }),
    metadata: (p) => ({ type: 'metadata', data: p as ContractReviewMetadata }),
  })
}
