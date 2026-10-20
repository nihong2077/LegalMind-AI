'use client'

/**
 * 案件视图（T2.4，替代旧 /cases）
 * 数据来源：协同群聊（GET /api/conversations type=group）+ 合同审查记录（本地按用户隔离存储）。
 * 渲染为「列表栏 + 详情栏」两列，与记忆页三栏 IA 一致。
 */
import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  ArrowRight,
  FileCheck,
  FolderOpen,
  Loader2,
  Search,
  Users,
} from 'lucide-react'
import { Conversation, listConversations } from '@/app/lib/collab'
import { getUsername } from '@/app/lib/api'
import { relativeTime } from '@/components/collab/format'
import { useCollabStore } from '@/store/useCollabStore'

interface ContractRecord {
  id: string
  title?: string
  description?: string
  riskLevel?: string
  createdAt?: string
}

interface CaseItem {
  id: string
  kind: 'group' | 'contract'
  title: string
  description: string
  caseType?: string | null
  members?: number
  updatedAt?: string | null
  raw: Conversation | ContractRecord
}

const CONTRACT_REVIEWS_KEY = 'legalmind_contract_reviews'

/** 合同审查记录按用户名隔离读取（与 DocumentUpload 写入键一致） */
function loadContractReviews(): ContractRecord[] {
  if (typeof window === 'undefined') return []
  const username = getUsername()
  const key = username ? `${CONTRACT_REVIEWS_KEY}:${username}` : CONTRACT_REVIEWS_KEY
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

export default function CasesPane() {
  const router = useRouter()
  const selectConversation = useCollabStore((s) => s.selectConversation)

  const [groups, setGroups] = useState<Conversation[]>([])
  const [contracts, setContracts] = useState<ContractRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'group' | 'contract'>('all')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    setContracts(loadContractReviews())
    let alive = true
    listConversations('active')
      .then((all) => {
        if (!alive) return
        setGroups(all.filter((c) => c.type === 'group'))
      })
      .catch((e) => {
        if (alive) setError(e instanceof Error ? e.message : '加载案件失败')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const cases = useMemo<CaseItem[]>(() => {
    const groupItems: CaseItem[] = groups.map((g) => ({
      id: g.id,
      kind: 'group',
      title: g.title || g.case_type || '协同群聊',
      description: g.case_type ? `案情类型：${g.case_type}` : '多智能体会商群聊',
      caseType: g.case_type,
      members: g.members?.length ?? 0,
      updatedAt: g.updated_at || g.created_at,
      raw: g,
    }))
    const contractItems: CaseItem[] = contracts.map((r) => ({
      id: r.id,
      kind: 'contract',
      title: r.title || '未命名合同',
      description: r.description || '合同审查记录',
      updatedAt: r.createdAt || null,
      raw: r,
    }))
    return [...groupItems, ...contractItems].sort((a, b) =>
      (b.updatedAt || '').localeCompare(a.updatedAt || ''),
    )
  }, [groups, contracts])

  const filtered = useMemo(() => {
    const kw = search.trim().toLowerCase()
    return cases.filter((c) => {
      if (filter !== 'all' && c.kind !== filter) return false
      if (kw && !c.title.toLowerCase().includes(kw) && !c.description.toLowerCase().includes(kw))
        return false
      return true
    })
  }, [cases, filter, search])

  const selected = cases.find((c) => c.id === selectedId) || null

  const openCase = async (c: CaseItem) => {
    if (c.kind === 'group') {
      await selectConversation(c.id)
      router.push('/messages')
    } else {
      router.push('/documents')
    }
  }

  return (
    <>
      <section className="w-[300px] h-screen bg-white border-r border-slate-200 flex flex-col flex-shrink-0">
        <header className="h-14 px-4 flex items-center justify-between border-b border-slate-200">
          <div className="flex items-center gap-2">
            <FolderOpen size={17} className="text-blue-500" />
            <h2 className="text-base font-semibold text-slate-800">案件</h2>
            <span className="text-[11px] text-slate-400">{cases.length} 个</span>
          </div>
        </header>

        <div className="p-3 border-b border-slate-100 space-y-2">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索案件"
              className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
            />
          </div>
          <div className="flex gap-1">
            {(['all', 'group', 'contract'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setFilter(t)}
                className={`flex-1 text-[11px] py-1 rounded-md transition-colors ${
                  filter === t ? 'bg-blue-100 text-blue-700 font-medium' : 'text-slate-500 hover:bg-slate-100'
                }`}
              >
                {t === 'all' ? '全部' : t === 'group' ? '协同群' : '合同审查'}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="h-full flex flex-col items-center justify-center gap-3 text-slate-400">
              <Loader2 size={22} className="animate-spin" />
              <p className="text-xs">加载案件中...</p>
            </div>
          )}

          {!loading && error && <div className="p-4 text-xs text-red-500">{error}</div>}

          {!loading && !error && filtered.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center gap-2 text-slate-400 px-6 text-center">
              <FolderOpen size={28} className="text-slate-300" />
              <p className="text-xs leading-relaxed">暂无案件记录</p>
            </div>
          )}

          {filtered.map((c) => {
            const active = c.id === selectedId
            return (
              <button
                key={`${c.kind}-${c.id}`}
                onClick={() => setSelectedId(c.id)}
                className={`w-full text-left px-4 py-3 border-b border-slate-50 transition-colors ${
                  active ? 'bg-blue-50/70' : 'hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  {c.kind === 'group' ? (
                    <Users size={12} className="text-blue-400 flex-shrink-0" />
                  ) : (
                    <FileCheck size={12} className="text-orange-400 flex-shrink-0" />
                  )}
                  <span className="text-xs font-medium text-slate-700 truncate flex-1">{c.title}</span>
                  <span className="text-[10px] text-slate-300 flex-shrink-0">
                    {relativeTime(c.updatedAt)}
                  </span>
                </div>
                <p className="text-[10px] text-slate-400 line-clamp-2 ml-5">{c.description}</p>
              </button>
            )
          })}
        </div>
      </section>

      <main className="flex-1 h-screen flex flex-col min-w-0 bg-slate-50 overflow-y-auto">
        {selected ? (
          <div className="p-8 max-w-3xl">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div
                  className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                    selected.kind === 'group' ? 'bg-blue-50' : 'bg-orange-50'
                  }`}
                >
                  {selected.kind === 'group' ? (
                    <Users size={20} className="text-blue-400" />
                  ) : (
                    <FileCheck size={20} className="text-orange-400" />
                  )}
                </div>
                <div>
                  <h3 className="text-base font-semibold text-slate-800">{selected.title}</h3>
                  <p className="text-[10px] text-slate-400">
                    {selected.kind === 'group' ? '多智能体协同群聊' : '合同审查'} ·{' '}
                    {relativeTime(selected.updatedAt)}
                  </p>
                </div>
              </div>
              <button
                onClick={() => openCase(selected)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 text-white text-xs hover:bg-blue-700 transition-colors"
              >
                {selected.kind === 'group' ? '进入会话' : '查看审查'}
                <ArrowRight size={12} />
              </button>
            </div>

            <div className="space-y-4">
              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <h4 className="text-xs font-semibold text-slate-500 mb-3">案件概要</h4>
                <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
                  {selected.description || '暂无描述'}
                </p>
              </div>
              {selected.kind === 'group' && (
                <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-2 text-xs">
                  {selected.caseType && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400">案情类型</span>
                      <span className="text-slate-600">{selected.caseType}</span>
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">参与成员</span>
                    <span className="text-slate-600">{selected.members} 位</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <FolderOpen size={48} className="text-slate-200 mx-auto mb-4" />
              <p className="text-sm text-slate-400">选择左侧案件查看详情</p>
            </div>
          </div>
        )}
      </main>
    </>
  )
}
