'use client'

/**
 * 协同会话实时流状态（T1.8-M2）：只维护**当前激活会话**一条 SSE 流。
 *
 * - 历史消息由 listMessages 拉取；SSE 从起点回放时依赖「按 id/去重 + 按
 *   event_key/metadata.message_id 合并」避免重复气泡（不清空已渲染历史）。
 * - 独立于旧 useChatStore（旧智能咨询链路不动）。
 */
import { create } from 'zustand'
import { ApiError, getUsername } from '@/app/lib/api'
import {
  CollabMessage,
  SenderType,
  generateMinutes as generateMinutesApi,
  listMessages,
  sendCollabMessage,
} from '@/app/lib/collab'
import { SseFrame, openConversationStream } from '@/app/lib/sse'

/** 交互卡片 payload（通用卡 / court 补证卡 / takeover 接管卡） */
export interface InteractionPayload {
  type: string
  question?: string
  turn_id?: string
  card_type?: string
  title?: string
  hint?: string
  agent_id?: string
  agent_name?: string
}

/** 正在流式生成的临时气泡（按 message_id 归并增量） */
export interface StreamBubble {
  sender_type: SenderType
  sender_id: string
  sender_name: string
  content: string
}

export interface StreamErrorState {
  code?: number
  message: string
  retryable: boolean
}

/** 工具辐条进度（法规/类案检索，SSE tool 事件） */
export interface ToolRun {
  agent_id: string
  agent_name: string
  tool: string
  status: string
  query: string
  result_count?: number
  elapsed_ms?: number
}

interface CollabStreamState {
  conversationId: string | null
  messages: CollabMessage[]
  streams: Record<string, StreamBubble>
  /** 当前轮次的工具辐条进度（running/done/error），turn 结束清空 */
  toolRuns: ToolRun[]
  phase: string | null
  /** status 事件的中文文案（如「会商进行中…」） */
  phaseText: string | null
  pending: InteractionPayload | null
  turnStatus: string | null
  /** 当前（最近）轮次 id，供右栏 Agent 时间线/checkpoints 使用 */
  turnId: string | null
  lastEventId: string
  error: StreamErrorState | null
  sending: boolean
  connected: boolean
  loadingHistory: boolean
  /** 上一条已发送文本（供失败重试） */
  lastSentText: string

  open: (conversationId: string) => Promise<void>
  close: () => void
  handleFrame: (f: SseFrame) => void
  send: (content: string) => Promise<void>
  handBack: () => Promise<void>
  /** 结束会商（用户主权，仅挂起轮次可用）：注入 conclude 收尾 */
  conclude: () => Promise<void>
  /** 生成会商纪要（手动触发）：返回的纪要不落聊天气泡式乐观追加，直接并入列表 */
  generateMinutes: () => Promise<void>
  retryLast: () => Promise<void>
}

// ---------------- 辅助 ----------------

function sortByCreated(messages: CollabMessage[]): CollabMessage[] {
  return [...messages].sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''))
}

function toStreamError(e: unknown): StreamErrorState {
  if (e instanceof ApiError) return { code: e.code, message: e.message, retryable: e.retryable }
  if (e instanceof Error) return { message: e.message, retryable: false }
  return { message: '发送失败', retryable: false }
}

/**
 * 归一化 incoming SSE `message` 事件为 CollabMessage。
 * 兼容扁平（sender_type/sender_id/sender_name）与嵌套（sender:{type,id,name}）两种形状。
 */
function normalizeIncoming(raw: any, conversationId: string | null): CollabMessage | null {
  if (!raw || typeof raw !== 'object') return null
  const id = raw.id
  if (!id) return null
  const sender = raw.sender && typeof raw.sender === 'object' ? raw.sender : null
  return {
    id: String(id),
    conversation_id: String(raw.conversation_id ?? conversationId ?? ''),
    sender_type: (raw.sender_type ?? sender?.type ?? 'agent') as SenderType,
    sender_id: String(raw.sender_id ?? sender?.id ?? ''),
    sender_name: raw.sender_name ?? sender?.name ?? null,
    content: typeof raw.content === 'string' ? raw.content : '',
    msg_type: typeof raw.msg_type === 'string' ? raw.msg_type : 'text',
    round: typeof raw.round === 'number' ? raw.round : 0,
    event_key: raw.event_key ?? null,
    fork_parent_message_id: raw.fork_parent_message_id ?? null,
    metadata: raw.metadata && typeof raw.metadata === 'object' ? raw.metadata : {},
    created_at: typeof raw.created_at === 'string' ? raw.created_at : new Date().toISOString(),
  }
}

// 单例流句柄与兜底定时器（模块级，避免进入 React 渲染）
let activeClose: (() => void) | null = null
let unlockTimer: ReturnType<typeof setTimeout> | null = null
// open 序号：用于丢弃「被后续 open/close 取消」的滞后异步结果（切换会话/StrictMode 双调用）
let openToken = 0

export const useCollabStreamStore = create<CollabStreamState>((set, get) => {
  const clearUnlockTimer = () => {
    if (unlockTimer !== null) {
      clearTimeout(unlockTimer)
      unlockTimer = null
    }
  }

  /** 发送后若 1.5s 内无任何 SSE 事件，兜底解锁输入 */
  const armUnlockTimer = () => {
    clearUnlockTimer()
    unlockTimer = setTimeout(() => {
      unlockTimer = null
      if (get().sending) set({ sending: false })
    }, 1500)
  }

  return {
    conversationId: null,
    messages: [],
    streams: {},
    toolRuns: [],
    phase: null,
    phaseText: null,
    pending: null,
    turnStatus: null,
    turnId: null,
    lastEventId: '',
    error: null,
    sending: false,
    connected: false,
    loadingHistory: false,
    lastSentText: '',

    open: async (conversationId) => {
      const token = ++openToken
      if (activeClose) {
        activeClose()
        activeClose = null
      }
      clearUnlockTimer()
      set({
        conversationId,
        messages: [],
        streams: {},
    toolRuns: [],
        phase: null,
        phaseText: null,
        pending: null,
        turnStatus: null,
        turnId: null,
        lastEventId: '',
        error: null,
        sending: false,
        connected: false,
        loadingHistory: true,
      })

      // 1) 拉历史（limit=50），按 created_at 升序铺开
      try {
        const page = await listMessages(conversationId, { limit: 50 })
        if (token !== openToken) return // 已被后续 open/close 取消
        set({ messages: sortByCreated(page.messages || []), loadingHistory: false })
      } catch (e) {
        if (token !== openToken) return
        set({ loadingHistory: false, error: toStreamError(e) })
      }

      if (token !== openToken) return

      // 2) 从 Stream 起点回放：lastEventId 传空，靠 id/合并逻辑去重
      activeClose = openConversationStream({
        conversationId,
        lastEventId: '',
        onFrame: (f) => get().handleFrame(f),
        onOpen: () => set({ connected: true }),
        onError: (e) =>
          set({ error: { message: e.message, retryable: e.retryable }, connected: false }),
      }).close
    },

    close: () => {
      openToken += 1 // 使进行中的 open 异步流程失效
      if (activeClose) {
        activeClose()
        activeClose = null
      }
      clearUnlockTimer()
      set({
        conversationId: null,
        messages: [],
        streams: {},
    toolRuns: [],
        phase: null,
        phaseText: null,
        pending: null,
        turnStatus: null,
        turnId: null,
        lastEventId: '',
        error: null,
        sending: false,
        connected: false,
        loadingHistory: false,
      })
    },

    handleFrame: (f) => {
      clearUnlockTimer() // 有事件到达 → 兜底定时器失效，交给 done/message 解锁
      if (f.id) set({ lastEventId: f.id })

      switch (f.event) {
        case 'message_start': {
          const mid = String(f.data?.message_id ?? '')
          if (!mid) return
          set((s) => {
            // 历史已含同 message_id（metadata.message_id）→ 回放重复，跳过
            const persisted = s.messages.some(
              (m) => String((m.metadata || {}).message_id ?? '') === mid,
            )
            if (persisted) return {}
            const sender = (f.data?.sender || {}) as Record<string, unknown>
            return {
              streams: {
                ...s.streams,
                [mid]: {
                  sender_type: (sender.type as SenderType) || 'agent',
                  sender_id: String(sender.id ?? ''),
                  sender_name: String(sender.name ?? ''),
                  content: '',
                },
              },
            }
          })
          return
        }

        case 'message_delta': {
          const mid = String(f.data?.message_id ?? '')
          const delta = typeof f.data?.delta === 'string' ? f.data.delta : ''
          if (!mid || !delta) return
          set((s) => {
            const current = s.streams[mid]
            const next: StreamBubble = current
              ? { ...current, content: current.content + delta }
              : { sender_type: 'agent', sender_id: '', sender_name: '', content: delta }
            return { streams: { ...s.streams, [mid]: next } }
          })
          return
        }

        case 'message_end': {
          const mid = String(f.data?.message_id ?? '')
          if (!mid) return
          const content = typeof f.data?.content === 'string' ? f.data.content : ''
          set((s) => {
            const current = s.streams[mid]
            const next: StreamBubble = current
              ? { ...current, content: content || current.content }
              : {
                  sender_type: ((f.data?.sender?.type as SenderType) ||
                    'agent') as SenderType,
                  sender_id: String(f.data?.sender?.id ?? ''),
                  sender_name: String(f.data?.sender?.name ?? ''),
                  content,
                }
            return { streams: { ...s.streams, [mid]: next } }
          })
          return
        }

        case 'message': {
          const msg = normalizeIncoming(f.data, get().conversationId)
          if (!msg) return
          set((s) => {
            const streams = { ...s.streams }
            // 1) 命中临时流式气泡（按 metadata.message_id，回退 sender+content）
            const metaMid = String((msg.metadata || {}).message_id ?? '')
            let matchedKey: string | null = metaMid && streams[metaMid] ? metaMid : null
            if (!matchedKey) {
              for (const [key, bubble] of Object.entries(streams)) {
                if (
                  bubble.sender_id === msg.sender_id &&
                  bubble.sender_type === msg.sender_type &&
                  bubble.content.trim() !== '' &&
                  bubble.content.trim() === msg.content.trim()
                ) {
                  matchedKey = key
                  break
                }
              }
            }
            if (matchedKey) delete streams[matchedKey]

            // 2) 已存在同 id → 原地更新
            const idx = s.messages.findIndex((m) => m.id === msg.id)
            if (idx >= 0) {
              const next = [...s.messages]
              next[idx] = { ...next[idx], ...msg }
              return { messages: sortByCreated(next), streams }
            }

            // 3) 乐观 user 消息（local-*）→ 用落库消息替换
            const optimisticIdx = s.messages.findIndex(
              (m) =>
                m.id.startsWith('local-') &&
                m.sender_type === msg.sender_type &&
                m.content === msg.content,
            )
            const next =
              optimisticIdx >= 0
                ? s.messages.map((m, i) => (i === optimisticIdx ? msg : m))
                : [...s.messages, msg]
            return { messages: sortByCreated(next), streams }
          })
          if (msg.sender_type === 'user') set({ sending: false }) // 用户发言已回显 → 解锁
          return
        }

        case 'tool': {
          const d = (f.data || {}) as Record<string, unknown>
          const agentId = String(d.agent_id ?? '')
          if (!agentId) return
          const entry: ToolRun = {
            agent_id: agentId,
            agent_name: String(d.agent_name ?? agentId),
            tool: String(d.tool ?? ''),
            status: String(d.status ?? 'running'),
            query: typeof d.query === 'string' ? d.query : '',
            result_count: typeof d.result_count === 'number' ? d.result_count : undefined,
            elapsed_ms: typeof d.elapsed_ms === 'number' ? d.elapsed_ms : undefined,
          }
          set((s) => ({
            toolRuns: [...s.toolRuns.filter((t) => t.agent_id !== agentId), entry],
          }))
          return
        }

        case 'status': {
          set({
            phase: typeof f.data?.phase === 'string' ? f.data.phase : null,
            phaseText: typeof f.data?.message === 'string' ? f.data.message : null,
            turnId: typeof f.data?.turn_id === 'string' ? f.data.turn_id : get().turnId,
          })
          return
        }

        case 'interaction_required': {
          set({
            pending: (f.data as InteractionPayload) || null,
            phase: null,
            phaseText: null,
            turnId: typeof f.data?.turn_id === 'string' ? f.data.turn_id : get().turnId,
            sending: false, // 轮次已挂起等待用户输入 → 解锁输入
          })
          return
        }

        case 'done': {
          set({
            turnStatus: 'completed',
            phase: null,
            phaseText: null,
            pending: null,
            toolRuns: [],
            turnId: typeof f.data?.turn_id === 'string' ? f.data.turn_id : get().turnId,
            sending: false,
          })
          return
        }

        case 'error': {
          set({
            error: {
              code: typeof f.data?.code === 'number' ? f.data.code : undefined,
              message: typeof f.data?.message === 'string' ? f.data.message : '实时连接异常',
              retryable: f.data?.retryable === true,
            },
            sending: false,
          })
          return
        }

        default:
          return
      }
    },

    send: async (content) => {
      const text = content.trim()
      if (!text) return
      const { conversationId } = get()
      if (!conversationId) return

      const localId = `local-${Date.now()}`
      const who = getUsername() || 'user'
      const optimistic: CollabMessage = {
        id: localId,
        conversation_id: conversationId,
        sender_type: 'user',
        sender_id: who,
        sender_name: who,
        content: text,
        msg_type: 'text',
        round: 0,
        event_key: null,
        fork_parent_message_id: null,
        metadata: {},
        created_at: new Date().toISOString(),
      }

      set((s) => ({
        messages: sortByCreated([...s.messages, optimistic]),
        sending: true,
        error: null,
        lastSentText: text,
      }))

      try {
        const res = await sendCollabMessage(conversationId, { content: text })
        if (res.turn_id) set({ turnId: res.turn_id })
        // 用落库消息替换临时乐观消息（按临时 id 定位）
        if (res.message) {
          const serverMsg = res.message
          set((s) => ({
            messages: sortByCreated(
              s.messages.map((m) => (m.id === localId ? { ...serverMsg } : m)),
            ),
          }))
        }
        armUnlockTimer()
      } catch (e) {
        set({ error: toStreamError(e), sending: false })
      }
    },

    handBack: async () => {
      const { conversationId } = get()
      if (!conversationId) return
      set({ sending: true, error: null })
      try {
        // 空 content 仅 hand_back 场景合法；此为控制动作，不落聊天气泡
        await sendCollabMessage(conversationId, { content: '', metadata: { hand_back: true } })
        set({ pending: null, phase: null, phaseText: null, sending: false })
      } catch (e) {
        set({ error: toStreamError(e), sending: false })
      }
    },

    conclude: async () => {
      const { conversationId } = get()
      if (!conversationId) return
      set({ sending: true, error: null })
      try {
        // 控制动作：空 content + metadata.conclude；不落聊天气泡
        await sendCollabMessage(conversationId, { content: '', metadata: { conclude: true } })
        set({ pending: null, phase: null, phaseText: null, sending: false })
      } catch (e) {
        set({ error: toStreamError(e), sending: false })
      }
    },

    generateMinutes: async () => {
      const { conversationId } = get()
      if (!conversationId) return
      set({ sending: true, error: null })
      try {
        const res = await generateMinutesApi(conversationId)
        if (res.message) {
          const msg = res.message
          set((s) => ({
            messages: sortByCreated([...s.messages.filter((m) => m.id !== msg.id), msg]),
          }))
        }
      } catch (e) {
        set({ error: toStreamError(e) })
      } finally {
        set({ sending: false })
      }
    },

    retryLast: async () => {
      const { error, lastSentText } = get()
      if (!error || !lastSentText) return
      set({ error: null })
      await get().send(lastSentText)
    },
  }
})
