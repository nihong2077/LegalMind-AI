'use client'

/**
 * 案情搜索页（T3.2）
 * 统一搜索框 + Tab（全部/法规/类案/我的记忆/会话记录）；
 * 结果可「转发到…」（上下文卡片，不触发轮次）与「引用并新建协同群」；
 * 「知识库浏览」为次级入口（替代旧 /knowledge）。
 */
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { BookOpen, Search as SearchIcon } from 'lucide-react'
import IconRail from '@/components/collab/IconRail'
import SearchBar from '@/components/search/SearchBar'
import SearchResults from '@/components/search/SearchResults'
import ForwardDialog from '@/components/search/ForwardDialog'
import NewGroupFromQuoteDialog from '@/components/search/NewGroupFromQuoteDialog'
import KnowledgeBrowsePanel from '@/components/search/KnowledgeBrowsePanel'
import { MessageResult, SearchResult } from '@/app/lib/search'
import { useCollabStore } from '@/store/useCollabStore'

export default function SearchPage() {
  const router = useRouter()
  const selectConversation = useCollabStore((s) => s.selectConversation)
  const [browseOpen, setBrowseOpen] = useState(false)
  const [forwardTarget, setForwardTarget] = useState<SearchResult | null>(null)
  const [quoteTarget, setQuoteTarget] = useState<SearchResult | null>(null)

  const openMessage = async (r: MessageResult) => {
    await selectConversation(r.conversation_id)
    router.push('/messages')
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <IconRail />

      <main className="flex-1 flex flex-col min-w-0 bg-slate-50">
        <header className="h-14 px-6 flex items-center justify-between border-b border-slate-200 bg-white flex-shrink-0">
          <div className="flex items-center gap-2">
            <SearchIcon size={18} className="text-blue-500" />
            <h1 className="text-base font-semibold text-slate-800">案情搜索</h1>
            <span className="text-[11px] text-slate-400">法规 · 类案 · 记忆 · 会话</span>
          </div>
          <button
            onClick={() => setBrowseOpen((v) => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-colors ${
              browseOpen
                ? 'bg-blue-50 text-blue-600'
                : 'border border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}
          >
            <BookOpen size={14} />
            知识库浏览
          </button>
        </header>

        {browseOpen ? (
          <KnowledgeBrowsePanel onClose={() => setBrowseOpen(false)} />
        ) : (
          <>
            <div className="px-6 pt-5 pb-4 flex-shrink-0">
              <SearchBar />
            </div>
            <SearchResults
              onForward={setForwardTarget}
              onQuote={setQuoteTarget}
              onOpenMessage={openMessage}
            />
          </>
        )}
      </main>

      <ForwardDialog result={forwardTarget} onClose={() => setForwardTarget(null)} />
      <NewGroupFromQuoteDialog result={quoteTarget} onClose={() => setQuoteTarget(null)} />
    </div>
  )
}
