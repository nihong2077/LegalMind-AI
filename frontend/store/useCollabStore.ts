'use client'

/**
 * 消息中心状态（T1.8）：会话列表 / Agent 与模板目录 / 当前选中会话 / 右栏开关。
 * 独立于旧 useChatStore（旧智能咨询链路不做改动）。
 */
import { create } from 'zustand'
import { ApiError } from '@/app/lib/api'
import {
  AgentInfo,
  Conversation,
  TemplateCard,
  getConversation,
  listAgents,
  listConversations,
  listTemplates,
} from '@/app/lib/collab'

interface CollabState {
  conversations: Conversation[]
  agents: AgentInfo[]
  templates: TemplateCard[]
  loading: boolean
  catalogLoaded: boolean
  error: string | null
  selectedId: string | null
  rightRailOpen: boolean

  fetchConversations: () => Promise<void>
  fetchCatalog: () => Promise<void>
  selectConversation: (id: string | null) => Promise<void>
  setRightRailOpen: (open: boolean) => void
  toggleRightRail: () => void
  /** 新建/变更会话后并入列表（按 updated_at 倒序） */
  upsertConversation: (conversation: Conversation) => void
}

function errText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return '加载失败'
}

function sortConversations(items: Conversation[]): Conversation[] {
  return [...items].sort((a, b) => {
    const ta = a.updated_at || a.created_at || ''
    const tb = b.updated_at || b.created_at || ''
    return tb.localeCompare(ta)
  })
}

export const useCollabStore = create<CollabState>((set, get) => ({
  conversations: [],
  agents: [],
  templates: [],
  loading: false,
  catalogLoaded: false,
  error: null,
  selectedId: null,
  rightRailOpen: true,

  fetchConversations: async () => {
    set({ loading: true, error: null })
    try {
      const conversations = await listConversations('active')
      set({ conversations: sortConversations(conversations), loading: false })
      // 选中项被删除/归档时清理
      const { selectedId } = get()
      if (selectedId && !conversations.some((c) => c.id === selectedId)) {
        set({ selectedId: null })
      }
    } catch (e) {
      set({ loading: false, error: errText(e) })
    }
  },

  fetchCatalog: async () => {
    if (get().catalogLoaded) return
    try {
      const [agents, templates] = await Promise.all([listAgents(), listTemplates()])
      set({ agents, templates, catalogLoaded: true })
    } catch (e) {
      set({ error: errText(e) })
    }
  },

  selectConversation: async (id) => {
    set({ selectedId: id })
    if (!id) return
    // 列表已带 members；仍拉一次详情以拿到最新成员/扮演角色
    try {
      const fresh = await getConversation(id)
      set((s) => ({
        conversations: sortConversations(
          s.conversations.map((c) => (c.id === fresh.id ? fresh : c)),
        ),
      }))
    } catch {
      // 详情刷新失败不阻断选中（沿用列表缓存）
    }
  },

  setRightRailOpen: (open) => set({ rightRailOpen: open }),
  toggleRightRail: () => set((s) => ({ rightRailOpen: !s.rightRailOpen })),

  upsertConversation: (conversation) =>
    set((s) => {
      const exists = s.conversations.some((c) => c.id === conversation.id)
      const next = exists
        ? s.conversations.map((c) => (c.id === conversation.id ? conversation : c))
        : [conversation, ...s.conversations]
      return { conversations: sortConversations(next) }
    }),
}))
