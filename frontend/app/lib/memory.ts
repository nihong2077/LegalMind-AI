/**
 * 长期记忆前端数据层（T2.4）
 *
 * 对齐后端 `routers/memory.py`（前缀 /api/memories，统一信封）：
 * 总开关 GET/PUT /setting、列表 GET ""、CRUD GET/POST/PATCH/DELETE /{id}。
 * 全部走 `request` 解包信封，失败抛 ApiError。
 */
import { request } from './http'

export type MemoryScope = 'user' | 'case'
export type MemoryStatus = 'active' | 'archived'

export interface MemoryRecord {
  id: string
  user_id: string
  scope: MemoryScope
  case_id: string | null
  memory_type: string
  content: string
  summary: string | null
  importance: number
  source_conversation_id: string | null
  source_message_id: string | null
  status: MemoryStatus
  /** 星标/置顶（T2.4 新增后端字段） */
  starred: boolean
  embedding_status: string
  created_at: string | null
  updated_at: string | null
}

export interface MemoryListParams {
  scope?: MemoryScope
  memory_type?: string
  case_id?: string
  status?: MemoryStatus
  starred?: boolean
  q?: string
  limit?: number
  offset?: number
}

export interface MemoryPage {
  memories: MemoryRecord[]
  total: number
  limit: number
  offset: number
}

export interface CreateMemoryBody {
  scope?: MemoryScope
  memory_type: string
  content: string
  summary?: string | null
  importance?: number
  case_id?: string | null
  source_conversation_id?: string | null
  source_message_id?: string | null
  starred?: boolean
}

export interface UpdateMemoryBody {
  content?: string
  summary?: string | null
  importance?: number
  memory_type?: string
  status?: MemoryStatus
  starred?: boolean
}

/** 分类 Tab：key='all' 表示不按类型过滤（与后端 memory_type 值对齐） */
export const MEMORY_TYPE_TABS: { key: string; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'background', label: '用户画像' },
  { key: 'fact', label: '案件事实' },
  { key: 'demand', label: '诉求与底线' },
  { key: 'timeline', label: '时间节点' },
  { key: 'preference', label: '策略偏好' },
]

export function memoryTypeLabel(type: string): string {
  return MEMORY_TYPE_TABS.find((t) => t.key === type)?.label || type
}

export async function listMemories(params: MemoryListParams = {}): Promise<MemoryPage> {
  const search = new URLSearchParams()
  if (params.scope) search.set('scope', params.scope)
  if (params.memory_type) search.set('memory_type', params.memory_type)
  if (params.case_id) search.set('case_id', params.case_id)
  if (params.status) search.set('status', params.status)
  if (params.starred !== undefined) search.set('starred', String(params.starred))
  if (params.q) search.set('q', params.q)
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  const qs = search.toString()
  return request<MemoryPage>(`/api/memories${qs ? `?${qs}` : ''}`)
}

export async function getMemory(memoryId: string): Promise<MemoryRecord> {
  return request<MemoryRecord>(`/api/memories/${memoryId}`)
}

export async function createMemory(body: CreateMemoryBody): Promise<MemoryRecord> {
  return request<MemoryRecord>('/api/memories', { method: 'POST', body })
}

export async function updateMemory(
  memoryId: string,
  body: UpdateMemoryBody,
): Promise<MemoryRecord> {
  return request<MemoryRecord>(`/api/memories/${memoryId}`, { method: 'PATCH', body })
}

export async function deleteMemory(memoryId: string): Promise<{ id: string }> {
  return request<{ id: string }>(`/api/memories/${memoryId}`, { method: 'DELETE' })
}

export async function getMemorySetting(): Promise<{ enabled: boolean }> {
  return request<{ enabled: boolean }>('/api/memories/setting')
}

export async function setMemorySetting(enabled: boolean): Promise<{ enabled: boolean }> {
  return request<{ enabled: boolean }>('/api/memories/setting', {
    method: 'PUT',
    body: { enabled },
  })
}
