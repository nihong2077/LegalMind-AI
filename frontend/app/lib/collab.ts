/**
 * 协同会话（消息中心）前端数据层（T1.8）
 *
 * 只承载 T1.1/T1.2 已交付的只读与写入契约：会话 / 成员 / Agent 注册表 /
 * 案情模板。SSE 流式与轮次 fork 由后续里程碑（lib/sse.ts）补充。
 * 统一走 `request` 解包信封，失败抛 ApiError。
 */
import { request } from './http'

// ---------------- 类型 ----------------

export interface AgentInfo {
  agent_id: string
  name: string
  avatar?: string | null
  role_label?: string | null
  description?: string | null
  skill_ref?: string | null
  persona?: string | null
  model_pref?: Record<string, unknown>
  is_tool: boolean
  sort_order: number
  enabled: boolean
}

export interface ConversationMember {
  agent_id: string
  role: 'host' | 'member'
  is_auto: boolean
  joined_at?: string | null
  name?: string
  avatar?: string | null
  role_label?: string | null
  is_tool?: boolean
  sort_order?: number
}

export interface Conversation {
  id: string
  user_id: string
  type: 'direct' | 'group'
  case_type?: string | null
  title?: string | null
  status: 'active' | 'archived'
  /** 用户扮演的 Agent（仅群聊；空＝不扮演） */
  my_role?: string | null
  /** 单聊目标 Agent（仅 direct） */
  target_agent_id?: string | null
  created_at?: string | null
  updated_at?: string | null
  members: ConversationMember[]
}

export type SenderType = 'user' | 'agent' | 'host' | 'tool' | 'system'

export interface CollabMessage {
  id: string
  conversation_id: string
  sender_type: SenderType
  sender_id: string
  sender_name?: string | null
  content: string
  msg_type: string
  round: number
  event_key?: string | null
  fork_parent_message_id?: string | null
  metadata?: Record<string, unknown>
  created_at?: string | null
}

export interface TemplateRosterItem {
  agent_id: string
  name?: string
  role_label?: string
  is_tool?: boolean
  stage?: string
  order?: number
}

export interface TemplateCard {
  case_type: string
  name: string
  icon?: string
  description?: string
  host_agent_id?: string
  roster?: { agent_id: string; stage?: string; order?: number }[]
  roster_summary?: TemplateRosterItem[]
  max_rounds?: number
  opening_enabled?: boolean
  minutes_enabled?: boolean
  adapter?: string
  enabled?: boolean
}

// ---------------- 只读接口 ----------------

export async function listConversations(status?: 'active' | 'archived'): Promise<Conversation[]> {
  const qs = status ? `?status=${status}` : ''
  const data = await request<{ conversations: Conversation[]; total: number }>(
    `/api/conversations${qs}`,
  )
  return data.conversations || []
}

export async function getConversation(conversationId: string): Promise<Conversation> {
  return request<Conversation>(`/api/conversations/${conversationId}`)
}

export async function listAgents(params: { isTool?: boolean; q?: string } = {}): Promise<AgentInfo[]> {
  const search = new URLSearchParams()
  if (params.isTool !== undefined) search.set('is_tool', String(params.isTool))
  if (params.q) search.set('q', params.q)
  const qs = search.toString()
  const data = await request<{ agents: AgentInfo[]; total: number }>(
    `/api/agents${qs ? `?${qs}` : ''}`,
  )
  return data.agents || []
}

export async function listTemplates(): Promise<TemplateCard[]> {
  const data = await request<{ templates: TemplateCard[]; total: number }>('/api/agents/templates')
  return data.templates || []
}

// ---------------- 建群向导（T1.8-M3） ----------------

/** 创建会话请求体（POST /api/conversations） */
export interface CreateConversationBody {
  type: 'direct' | 'group'
  /** 单聊目标 Agent（仅 direct 必填，∈ 已注册 Agent） */
  target_agent_id?: string
  /** 群聊案情模板（＝case_type；给了按模板自动铺 host 与 roster） */
  template_id?: string
  title?: string
  /** 群聊模板之外追加的 Agent（去重后并入 roster） */
  agent_ids?: string[]
  /** 群聊用户扮演的 agent_id（空＝不扮演，须 ∈ 最终 roster） */
  my_role?: string
}

/** 创建单聊 / 群聊；返回体即新建的 conversation */
export async function createConversation(body: CreateConversationBody): Promise<Conversation> {
  return request<Conversation>('/api/conversations', { method: 'POST', body })
}

/** 设置 / 撤销用户扮演角色（仅群聊；null ＝不扮演＝交还给 AI），返回最新会话 */
export async function setMyRole(
  conversationId: string,
  myRole: string | null,
): Promise<Conversation> {
  return request<Conversation>(`/api/conversations/${conversationId}/my_role`, {
    method: 'POST',
    body: { my_role: myRole },
  })
}

/** 追加群成员（返回新成员） */
export async function addMember(
  conversationId: string,
  agentId: string,
): Promise<ConversationMember> {
  return request<ConversationMember>(`/api/conversations/${conversationId}/members`, {
    method: 'POST',
    body: { agent_id: agentId },
  })
}

/** 移除群成员 */
export async function removeMember(conversationId: string, agentId: string): Promise<void> {
  await request(
    `/api/conversations/${conversationId}/members?agent_id=${encodeURIComponent(agentId)}`,
    { method: 'DELETE' },
  )
}

// ---------------- 消息 / SSE / 轮次（T1.8-M2） ----------------

/** 消息分页响应（GET /api/conversations/{id}/messages） */
export interface MessagePage {
  messages: CollabMessage[]
  next_before: string | null
  cached: boolean
}

/** 发送消息请求体（content 为空仅用于 hand_back 控制动作） */
export interface SendMessageBody {
  content: string
  msg_type?: string
  metadata?: Record<string, unknown>
}

/** 发送消息响应（POST /api/conversations/{id}/messages） */
export interface SendMessageResult {
  message: CollabMessage
  event_id: string
  turn_id: string
  status: string
}

/** SSE 短票据（POST /api/collab/conversations/{id}/events/ticket） */
export interface EventsTicket {
  events_token: string
  expires_in: number
}

/** 轮次 checkpoint 时间线条目（对齐 runner.list_checkpoints） */
export interface CheckpointItem {
  checkpoint_id: string | null
  step: number
  round: number
  directive: string | null
  reason: string | null
  force_stop_reason: string | null
  spoken: string[]
  next: string[]
  created_at: string | null
  is_latest: boolean
}

export interface TurnCheckpoints {
  turn_id: string
  status: string
  checkpoints: CheckpointItem[]
}

export interface ForkTurnBody {
  checkpoint_id: string
  update?: Record<string, unknown>
}

export interface ForkTurnResult {
  turn_id: string
  status: string
}

/** 拉取会话消息（首页命中服务端热缓存；before 游标翻历史页） */
export async function listMessages(
  conversationId: string,
  opts: { before?: string; limit?: number } = {},
): Promise<MessagePage> {
  const search = new URLSearchParams()
  if (opts.before) search.set('before', opts.before)
  if (opts.limit !== undefined) search.set('limit', String(opts.limit))
  const qs = search.toString()
  return request<MessagePage>(
    `/api/conversations/${conversationId}/messages${qs ? `?${qs}` : ''}`,
  )
}

/** 发送用户消息（起新轮次；若会话存在 running 轮次则返回 50901） */
export async function sendCollabMessage(
  conversationId: string,
  body: SendMessageBody,
): Promise<SendMessageResult> {
  return request<SendMessageResult>(`/api/conversations/${conversationId}/messages`, {
    method: 'POST',
    body,
  })
}

/** 换取一次性 SSE 短票据（EventSource 无法携带 Authorization 头，凭票据鉴权） */
export async function getEventsTicket(conversationId: string): Promise<EventsTicket> {
  return request<EventsTicket>(
    `/api/collab/conversations/${conversationId}/events/ticket`,
    { method: 'POST' },
  )
}

/** 列出某轮次的 checkpoint 时间线 */
export async function listCheckpoints(
  conversationId: string,
  turnId: string,
): Promise<TurnCheckpoints> {
  return request<TurnCheckpoints>(
    `/api/conversations/${conversationId}/turns/${turnId}/checkpoints`,
  )
}

/** 从指定 checkpoint 分叉重跑该轮次 */
export async function forkTurn(
  conversationId: string,
  turnId: string,
  body: ForkTurnBody,
): Promise<ForkTurnResult> {
  return request<ForkTurnResult>(
    `/api/conversations/${conversationId}/turns/${turnId}/fork`,
    { method: 'POST', body },
  )
}

/** 会商纪要生成结果（POST /api/conversations/{id}/minutes） */
export interface MinutesResult {
  message: CollabMessage | null
  event_id: string | null
  /** true 表示同一轮次已有纪要，直接复用（未重新生成） */
  reused: boolean
}

/** 手动生成《会商纪要》：书记员汇总本会话各方观点，token 级流式产出 */
export async function generateMinutes(conversationId: string): Promise<MinutesResult> {
  return request<MinutesResult>(`/api/conversations/${conversationId}/minutes`, {
    method: 'POST',
  })
}
