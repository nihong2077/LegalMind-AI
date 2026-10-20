'use client'

/**
 * 旧本地会话迁移引导（T4.2）
 *
 * 登录后在消息中心顶部提示：把旧 localStorage 会话一次性导入为服务端 direct 历史。
 * - 读 `legalmind_sessions:{username}`（与旧 useChatStore 同键），无内容则静默不显示；
 * - 已处理过（`legalmind_migrated:{username}`）不再提示；
 * - 「导入」逐会话调用 importConversation（不起轮次），完成后置标志并刷新会话列表；
 * - 零侵入：失败仅提示，不阻塞消息中心。
 */
import { useEffect, useState } from 'react'
import { importConversation } from '@/app/lib/collab'
import { getUsername } from '@/app/lib/http'
import { useCollabStore } from '@/store/useCollabStore'

interface LegacyMessage {
  role: string
  content: string
  timestamp?: string
}

interface LegacySession {
  id: string
  title?: string
  messages: LegacyMessage[]
}

const SESSIONS_BASE = 'legalmind_sessions'
const MIGRATED_BASE = 'legalmind_migrated'
// 与后端单次导入上限对齐（每条会话一次请求）
const MAX_SESSIONS = 20
const MAX_MESSAGES = 200

function storageKey(base: string, username: string): string {
  return `${base}:${username}`
}

function readLegacySessions(username: string): LegacySession[] {
  try {
    const raw = localStorage.getItem(storageKey(SESSIONS_BASE, username))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as LegacySession[]) : []
  } catch {
    return []
  }
}

export default function LegacyMigrationBanner() {
  const fetchConversations = useCollabStore((s) => s.fetchConversations)
  const [sessions, setSessions] = useState<LegacySession[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const username = getUsername()
    if (!username) return
    if (localStorage.getItem(storageKey(MIGRATED_BASE, username))) return
    // 只保留有可迁移消息的会话（旧 role 含 system，后端仅接受 user/assistant）
    const legacy = readLegacySessions(username).filter(
      (s) => Array.isArray(s.messages) && s.messages.some((m) => m.content?.trim()),
    )
    setSessions(legacy)
  }, [])

  const pendingCount = sessions.reduce((n, s) => n + s.messages.length, 0)

  const markMigrated = (username: string) => {
    try {
      localStorage.setItem(storageKey(MIGRATED_BASE, username), new Date().toISOString())
    } catch {
      // 存储满时忽略
    }
  }

  const handleImport = async () => {
    const username = getUsername()
    if (!username || busy) return
    setBusy(true)
    setError(null)
    try {
      for (const session of sessions.slice(0, MAX_SESSIONS)) {
        const messages = session.messages
          .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content?.trim())
          .slice(0, MAX_MESSAGES)
          .map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            ts: m.timestamp,
          }))
        if (messages.length === 0) continue
        await importConversation({ title: session.title || undefined, messages })
      }
      markMigrated(username)
      setSessions([])
      await fetchConversations()
    } catch {
      setError('导入失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  const handleLater = () => {
    const username = getUsername()
    if (username) markMigrated(username)
    setSessions([])
  }

  if (sessions.length === 0) return null

  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex justify-center p-3">
      <div className="pointer-events-auto flex flex-wrap items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 shadow-sm dark:border-amber-700 dark:bg-amber-950/80 dark:text-amber-100">
        <span>
          检测到 {sessions.length} 个本地旧会话（{pendingCount} 条消息），可导入到消息中心继续查看。
        </span>
        {error ? <span className="text-red-600 dark:text-red-400">{error}</span> : null}
        <button
          type="button"
          onClick={handleImport}
          disabled={busy}
          className="rounded bg-amber-600 px-3 py-1 text-white transition-opacity disabled:opacity-60"
        >
          {busy ? '导入中…' : '导入'}
        </button>
        <button
          type="button"
          onClick={handleLater}
          disabled={busy}
          className="rounded px-3 py-1 text-amber-800 underline-offset-2 hover:underline disabled:opacity-60 dark:text-amber-200"
        >
          稍后
        </button>
      </div>
    </div>
  )
}
