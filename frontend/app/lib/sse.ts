/**
 * 协同会话 SSE 客户端（T1.8-M2）
 *
 * 设计要点（对齐后端 routers/collab.py 契约）：
 * - 先 `POST .../events/ticket` 换 60s 一次性短票据；EventSource 无法携带
 *   Authorization 头，故凭票据经 query 鉴权，**URL 里不放 JWT**。
 * - 票据一次性：EventSource 自动重连会复用旧 URL（旧票据）→ 401。因此**自实现重连**：
 *   onerror 时 close 旧连接 → 重新换票 → 重建 EventSource，带指数退避
 *   （0.5s/1s/2s/4s…，上限 5 次），超过上限才回调 onError({retryable:true})。
 * - 用户显式 close() 后不得再重连（stopped 标志）。
 * - 帧 data 为 JSON 字符串；解析失败（ping/注释/脏数据）忽略。
 * - 按 `id`（Redis Stream id，严格单调）去重：`e.lastEventId` 存在且不大于已记录
 *   的最大 id 则丢弃，保证断线重连/回放「不丢不重」。
 */
import { API_BASE } from './http'
import { getEventsTicket } from './collab'

export type SseFrame = { id: string; event: string; data: any }

/** 后端会推送的事件名（含落库广播的 message；message 也是 EventSource 默认事件名） */
const EVENT_NAMES = [
  'message_start',
  'message_delta',
  'message_end',
  'status',
  'interaction_required',
  'message',
  'done',
  'error',
] as const

const MAX_RETRIES = 5
const BASE_DELAY_MS = 500

/** Redis Stream id 形如 `{ms}-{seq}`；按数值分段比较，退化时用字典序 */
function isNewerId(next: string, prev: string): boolean {
  if (!prev) return true
  if (!next) return false
  const [nextMs, nextSeq] = next.split('-')
  const [prevMs, prevSeq] = prev.split('-')
  const a = Number(nextMs)
  const b = Number(prevMs)
  if (Number.isFinite(a) && Number.isFinite(b) && a !== b) return a > b
  const c = Number(nextSeq || 0)
  const d = Number(prevSeq || 0)
  if (c !== d) return c > d
  return next > prev
}

export function openConversationStream(opts: {
  conversationId: string
  lastEventId?: string
  onFrame: (f: SseFrame) => void
  onOpen?: () => void
  onError?: (e: { message: string; retryable: boolean }) => void
}): { close: () => void } {
  const { conversationId, onFrame, onOpen, onError } = opts

  let stopped = false
  let es: EventSource | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let retries = 0
  let lastId = opts.lastEventId || ''

  const clearTimer = () => {
    if (retryTimer !== null) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  const teardown = () => {
    if (es) {
      es.close()
      es = null
    }
  }

  const handleFrame = (event: MessageEvent) => {
    if (stopped) return
    const id = event.lastEventId || ''
    if (id) {
      if (!isNewerId(id, lastId)) return // 重复/更旧事件丢弃
      lastId = id
    }
    let data: any
    try {
      data = JSON.parse(event.data)
    } catch {
      return // 非 JSON（ping/注释/脏数据）忽略
    }
    onFrame({ id, event: event.type, data })
  }

  const scheduleReconnect = () => {
    if (stopped) return
    if (retries >= MAX_RETRIES) {
      onError?.({ message: '实时连接中断，重连多次失败', retryable: true })
      return
    }
    const delay = BASE_DELAY_MS * 2 ** retries
    retries += 1
    clearTimer()
    retryTimer = setTimeout(() => {
      retryTimer = null
      void connect()
    }, delay)
  }

  const connect = async (): Promise<void> => {
    if (stopped) return
    teardown()

    let ticket: string
    try {
      const t = await getEventsTicket(conversationId)
      ticket = t.events_token
    } catch {
      if (stopped) return
      scheduleReconnect() // 换票失败也纳入退避重试
      return
    }
    if (stopped) return

    // 后端鉴权参数名为 events_token（非 ticket）。EventSource 不能带头，故票据走 query。
    let url = `${API_BASE}/api/collab/conversations/${conversationId}/events?events_token=${encodeURIComponent(ticket)}`
    if (lastId) url += `&last_id=${encodeURIComponent(lastId)}`

    const source = new EventSource(url)
    es = source

    source.onopen = () => {
      if (stopped) return
      retries = 0
      onOpen?.()
    }

    source.onerror = () => {
      if (stopped) return
      teardown()
      scheduleReconnect()
    }

    for (const name of EVENT_NAMES) {
      source.addEventListener(name, handleFrame as EventListener)
    }
  }

  void connect()

  return {
    close: () => {
      stopped = true
      clearTimer()
      teardown()
    },
  }
}
