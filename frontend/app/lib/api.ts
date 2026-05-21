const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
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

export interface StreamError {
  error: string
  message: string
}

function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('legalmind_token')
}

export function setToken(token: string): void {
  localStorage.setItem('legalmind_token', token)
}

export function clearToken(): void {
  localStorage.removeItem('legalmind_token')
}

export function isAuthenticated(): boolean {
  return !!getToken()
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE}/api/auth/token?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '登录失败' }))
    throw new Error(err.detail || '登录失败')
  }
  const data: TokenResponse = await res.json()
  setToken(data.access_token)
  return data
}

export async function chatCompletion(messages: ChatMessage[], model = 'deepseek-flash') {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ messages, model }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(err.detail || '请求失败')
  }
  return res.json()
}

export async function* chatStream(
  messages: ChatMessage[],
  model = 'deepseek-flash',
  signal?: AbortSignal,
): AsyncGenerator<{ type: 'chunk' | 'done' | 'error'; data: StreamChunk | StreamDone | StreamError }> {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ messages, model }),
    signal,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(err.detail || '请求失败')
  }

  const reader = res.body?.getReader()
  if (!reader) throw new Error('无法获取响应流')

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    let currentEvent = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        const rawData = line.slice(6)
        try {
          const parsed = JSON.parse(rawData)
          if (currentEvent === 'message') {
            yield { type: 'chunk', data: parsed as StreamChunk }
          } else if (currentEvent === 'done') {
            yield { type: 'done', data: parsed as StreamDone }
          } else if (currentEvent === 'error') {
            yield { type: 'error', data: parsed as StreamError }
          }
        } catch {
          // 忽略非 JSON 数据（如 ping）
        }
        currentEvent = ''
      }
    }
  }
}

export async function checkHealth(): Promise<{ status: string; redis?: unknown; litellm?: unknown }> {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) throw new Error('健康检查失败')
  return res.json()
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

async function authFetch(url: string, options?: RequestInit) {
  const token = getToken()
  if (!token) throw new Error('未登录')
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string> || {}),
    'Authorization': `Bearer ${token}`,
  }
  const res = await fetch(url, { ...options, headers })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(err.detail || '请求失败')
  }
  return res
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const res = await authFetch(`${API_BASE}/api/dashboard/stats`)
  return res.json()
}

export async function incrementStat(key: 'chat_count' | 'doc_count'): Promise<void> {
  await authFetch(`${API_BASE}/api/dashboard/stats/increment?key=${key}`, { method: 'POST' })
}

export async function getRecentCases(): Promise<CaseItem[]> {
  const res = await authFetch(`${API_BASE}/api/dashboard/cases`)
  return res.json()
}

export async function createCase(title: string, description = ''): Promise<CaseItem> {
  const res = await authFetch(
    `${API_BASE}/api/dashboard/cases?title=${encodeURIComponent(title)}&description=${encodeURIComponent(description)}`,
    { method: 'POST' },
  )
  return res.json()
}

export async function uploadDocument(file: File): Promise<DocumentItem> {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/api/documents/upload`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` },
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '上传失败' }))
    throw new Error(err.detail || '上传失败')
  }
  return res.json()
}

export async function listDocuments(): Promise<DocumentItem[]> {
  const res = await authFetch(`${API_BASE}/api/documents`)
  return res.json()
}

export async function getDocumentContent(docId: string): Promise<string> {
  const res = await authFetch(`${API_BASE}/api/documents/${docId}/content`)
  const data = await res.json()
  return data.content || data.text || ''
}

export async function analyzeDocument(docId: string): Promise<{ task_id: string; doc_id: string; status: string }> {
  const res = await authFetch(`${API_BASE}/api/documents/${docId}/analyze`, { method: 'POST' })
  return res.json()
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
  const res = await authFetch(`${API_BASE}/api/knowledge/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, domain, top_k: topK, use_hyde: true }),
  })
  return res.json()
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
  const res = await authFetch(`${API_BASE}/api/knowledge/list?${params}`)
  return res.json()
}

export interface DebateRequest {
  case_description: string
  evidence_summary?: string
  task_type?: string
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
  const res = await authFetch(`${API_BASE}/api/debate/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json()
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

export async function* debateStream(
  body: DebateRequest,
  signal?: AbortSignal,
): AsyncGenerator<{ type: 'chunk' | 'done' | 'error' | 'metadata'; data: DebateStreamChunk | DebateStreamDone | StreamError | DebateMetadata }> {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const res = await fetch(`${API_BASE}/api/debate/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(err.detail || '请求失败')
  }

  const reader = res.body?.getReader()
  if (!reader) throw new Error('无法获取响应流')

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    let currentEvent = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        const rawData = line.slice(6)
        try {
          const parsed = JSON.parse(rawData)
          if (currentEvent === 'message') {
            yield { type: 'chunk', data: parsed as DebateStreamChunk }
          } else if (currentEvent === 'done') {
            yield { type: 'done', data: parsed as DebateStreamDone }
          } else if (currentEvent === 'error') {
            yield { type: 'error', data: parsed as StreamError }
          } else if (currentEvent === 'metadata') {
            yield { type: 'metadata', data: parsed as DebateMetadata }
          }
        } catch {
          // 忽略非 JSON 数据
        }
        currentEvent = ''
      }
    }
  }
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
  const res = await authFetch(`${API_BASE}/api/contract/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json()
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
    summary?: string[]; clause_details?: string[];
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

export async function* contractReviewStream(
  body: ContractReviewRequest,
  signal?: AbortSignal,
): AsyncGenerator<{ type: 'chunk' | 'done' | 'error' | 'metadata'; data: { node: string; content: string } | ContractReviewDone | StreamError | ContractReviewMetadata }> {
  const token = getToken()
  if (!token) throw new Error('未登录')

  const res = await fetch(`${API_BASE}/api/contract/review/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(err.detail || '请求失败')
  }

  const reader = res.body?.getReader()
  if (!reader) throw new Error('无法获取响应流')

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    let currentEvent = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        const rawData = line.slice(6)
        try {
          const parsed = JSON.parse(rawData)
          if (currentEvent === 'message') {
            yield { type: 'chunk', data: parsed as { node: string; content: string } }
          } else if (currentEvent === 'done') {
            yield { type: 'done', data: parsed as ContractReviewDone }
          } else if (currentEvent === 'error') {
            yield { type: 'error', data: parsed as StreamError }
          } else if (currentEvent === 'metadata') {
            yield { type: 'metadata', data: parsed as ContractReviewMetadata }
          }
        } catch {
          // 忽略非 JSON 数据
        }
        currentEvent = ''
      }
    }
  }
}
