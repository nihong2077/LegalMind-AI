'use client'

/**
 * 统一搜索框（T3.2）
 * 受控于 useSearchStore.query；回车/点击「搜索」触发四路召回。
 */
import { Loader2, Search } from 'lucide-react'
import { useSearchStore } from '@/store/useSearchStore'

const HOT_SEARCHES = ['借款合同纠纷', '故意伤害罪量刑', '劳动合同解除赔偿', '违约责任']

export default function SearchBar() {
  const query = useSearchStore((s) => s.query)
  const setQuery = useSearchStore((s) => s.setQuery)
  const runSearch = useSearchStore((s) => s.runSearch)
  const loading = useSearchStore((s) => s.loading)

  const submit = () => {
    if (!query.trim() || loading) return
    void runSearch()
  }

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="relative">
        <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
          placeholder="统一搜索：法规 · 类案 · 我的记忆 · 会话记录"
          className="w-full bg-slate-50 border border-slate-200 rounded-xl pl-10 pr-24 py-2.5 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
        />
        <button
          onClick={submit}
          disabled={!query.trim() || loading}
          className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-blue-600 text-white text-xs hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading && <Loader2 size={13} className="animate-spin" />}
          搜索
        </button>
      </div>
      <div className="flex items-center gap-2 mt-2.5 flex-wrap">
        <span className="text-[10px] text-slate-400 flex-shrink-0">热门：</span>
        {HOT_SEARCHES.map((kw) => (
          <button
            key={kw}
            onClick={() => {
              setQuery(kw)
              void runSearch(kw)
            }}
            className="text-[11px] px-2.5 py-0.5 rounded-full border border-slate-200 text-slate-500 hover:text-blue-600 hover:border-blue-200 transition-colors"
          >
            {kw}
          </button>
        ))}
      </div>
    </div>
  )
}
