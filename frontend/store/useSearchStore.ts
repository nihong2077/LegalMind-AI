'use client'

/**
 * 案情搜索页状态（T3.2）
 *
 * 承载统一搜索：输入、Tab、四路结果、加载/错误态。
 * 后端一次并行返回四路（law/judge/memory/messages），Tab 仅做前端过滤，
 * 切换 Tab 不再触发请求。独立于 useMemoryStore / useCollabStore。
 */
import { create } from 'zustand'
import { ApiError } from '@/app/lib/api'
import {
  SearchTab,
  UnifiedSearchResponse,
  unifiedSearch,
} from '@/app/lib/search'

interface SearchState {
  /** 输入框内容 */
  query: string
  /** 最近一次已执行的查询（Tab 切换后标题/空态用） */
  activeQuery: string
  tab: SearchTab
  data: UnifiedSearchResponse | null
  loading: boolean
  error: string | null
  hasSearched: boolean

  setQuery: (q: string) => void
  setTab: (tab: SearchTab) => void
  runSearch: (override?: string) => Promise<void>
  reset: () => void
}

function errText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return '搜索失败'
}

export const useSearchStore = create<SearchState>((set, get) => ({
  query: '',
  activeQuery: '',
  tab: 'all',
  data: null,
  loading: false,
  error: null,
  hasSearched: false,

  setQuery: (q) => set({ query: q }),
  setTab: (tab) => set({ tab }),

  runSearch: async (override) => {
    const q = (override ?? get().query).trim()
    if (!q) return
    set({ loading: true, error: null, activeQuery: q, hasSearched: true })
    try {
      // 始终四路全查：Tab 过滤在前端完成，避免切换 Tab 重复请求
      const data = await unifiedSearch({ query: q, top_k: 5, message_limit: 10, use_hyde: true })
      set({ data, loading: false })
    } catch (e) {
      set({ loading: false, error: errText(e), data: null })
    }
  },

  reset: () =>
    set({
      query: '',
      activeQuery: '',
      tab: 'all',
      data: null,
      loading: false,
      error: null,
      hasSearched: false,
    }),
}))
