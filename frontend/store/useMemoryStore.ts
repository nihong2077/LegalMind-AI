'use client'

/**
 * 长期记忆页状态（T2.4）
 *
 * 承载记忆列表（分类/星标/归档/搜索过滤）、选中项、召回总开关。
 * 独立于 useCollabStore / useChatStore，仅服务 /memory 页。
 */
import { create } from 'zustand'
import { ApiError } from '@/app/lib/api'
import {
  CreateMemoryBody,
  MemoryRecord,
  UpdateMemoryBody,
  createMemory as apiCreate,
  deleteMemory as apiDelete,
  getMemorySetting,
  listMemories,
  setMemorySetting,
  updateMemory as apiUpdate,
} from '@/app/lib/memory'

type StatusFilter = 'active' | 'archived'

interface MemoryFilters {
  /** 'all' 或具体 memory_type */
  memoryType: string
  status: StatusFilter
  starredOnly: boolean
  query: string
}

interface MemoryState {
  items: MemoryRecord[]
  total: number
  loading: boolean
  error: string | null
  filters: MemoryFilters
  selectedId: string | null
  enabled: boolean
  settingLoaded: boolean

  fetchMemories: () => Promise<void>
  setFilters: (partial: Partial<MemoryFilters>) => void
  select: (id: string | null) => void
  fetchSetting: () => Promise<void>
  setEnabled: (enabled: boolean) => Promise<void>
  createMemory: (body: CreateMemoryBody) => Promise<MemoryRecord>
  updateMemory: (id: string, body: UpdateMemoryBody) => Promise<void>
  toggleStar: (id: string) => Promise<void>
  deleteMemory: (id: string) => Promise<void>
}

function errText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return '操作失败'
}

const DEFAULT_FILTERS: MemoryFilters = {
  memoryType: 'all',
  status: 'active',
  starredOnly: false,
  query: '',
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  items: [],
  total: 0,
  loading: false,
  error: null,
  filters: { ...DEFAULT_FILTERS },
  selectedId: null,
  enabled: true,
  settingLoaded: false,

  fetchMemories: async () => {
    const { filters } = get()
    set({ loading: true, error: null })
    try {
      const page = await listMemories({
        memory_type: filters.memoryType === 'all' ? undefined : filters.memoryType,
        status: filters.status,
        starred: filters.starredOnly ? true : undefined,
        q: filters.query.trim() || undefined,
        limit: 100,
      })
      const items = page.memories || []
      set({ items, total: page.total, loading: false })
      // 选中项已不在列表时清理
      const { selectedId } = get()
      if (selectedId && !items.some((m) => m.id === selectedId)) {
        set({ selectedId: null })
      }
    } catch (e) {
      set({ loading: false, error: errText(e) })
    }
  },

  setFilters: (partial) => {
    set((s) => ({ filters: { ...s.filters, ...partial } }))
    void get().fetchMemories()
  },

  select: (id) => set({ selectedId: id }),

  fetchSetting: async () => {
    try {
      const data = await getMemorySetting()
      set({ enabled: data.enabled, settingLoaded: true })
    } catch (e) {
      // 读取失败不阻断页面，按默认开启展示
      set({ settingLoaded: true, error: errText(e) })
    }
  },

  setEnabled: async (enabled) => {
    const prev = get().enabled
    set({ enabled })
    try {
      const data = await setMemorySetting(enabled)
      set({ enabled: data.enabled })
    } catch (e) {
      set({ enabled: prev, error: errText(e) })
    }
  },

  createMemory: async (body) => {
    const created = await apiCreate(body)
    await get().fetchMemories()
    set({ selectedId: created.id })
    return created
  },

  updateMemory: async (id, body) => {
    const updated = await apiUpdate(id, body)
    set((s) => ({ items: s.items.map((m) => (m.id === id ? updated : m)) }))
  },

  toggleStar: async (id) => {
    const current = get().items.find((m) => m.id === id)
    if (!current) return
    const updated = await apiUpdate(id, { starred: !current.starred })
    set((s) => ({ items: s.items.map((m) => (m.id === id ? updated : m)) }))
    // 置顶排序生效需重新拉取
    void get().fetchMemories()
  },

  deleteMemory: async (id) => {
    await apiDelete(id)
    set((s) => ({
      items: s.items.filter((m) => m.id !== id),
      total: Math.max(0, s.total - 1),
      selectedId: s.selectedId === id ? null : s.selectedId,
    }))
  },
}))
