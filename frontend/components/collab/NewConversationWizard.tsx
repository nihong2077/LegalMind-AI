'use client'

/**
 * 建群向导（T1.8-M3）
 *
 * 两条入口：
 *  - 单聊「智能咨询」：选 1 个 Agent → POST /api/conversations {type:direct, target_agent_id}
 *  - 群聊「模拟法庭/会商」：选案情模板 → 确认/追加成员 + 选扮演角色 →
 *    POST /api/conversations {type:group, template_id, agent_ids, my_role}
 *
 * 模板 roster 由后端按 template_id 自动铺开（含 host），此处只做展示与「追加」；
 * 移除模板成员需会话创建后用 DELETE /members（M4 群管理承接）。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  Check,
  Loader2,
  MessagesSquare,
  Plus,
  Search,
  User,
  Users,
  X,
} from 'lucide-react'
import { ApiError } from '@/app/lib/api'
import { Conversation, TemplateCard, createConversation } from '@/app/lib/collab'
import { useCollabStore } from '@/store/useCollabStore'
import Avatar from './Avatar'

interface NewConversationWizardProps {
  open: boolean
  onClose: () => void
}

type Step = 'entry' | 'direct' | 'template' | 'roster'

interface RosterEntry {
  agent_id: string
  name?: string
  role_label?: string
  is_tool?: boolean
  role: 'host' | 'member'
  /** 由用户手动追加（模板之外） */
  extra: boolean
}

function errText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return '创建失败'
}

export default function NewConversationWizard({ open, onClose }: NewConversationWizardProps) {
  const agents = useCollabStore((s) => s.agents)
  const templates = useCollabStore((s) => s.templates)
  const catalogLoaded = useCollabStore((s) => s.catalogLoaded)
  const fetchCatalog = useCollabStore((s) => s.fetchCatalog)
  const upsertConversation = useCollabStore((s) => s.upsertConversation)
  const selectConversation = useCollabStore((s) => s.selectConversation)

  const [step, setStep] = useState<Step>('entry')
  const [keyword, setKeyword] = useState('')
  const [directAgentId, setDirectAgentId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [template, setTemplate] = useState<TemplateCard | null>(null)
  const [extraIds, setExtraIds] = useState<string[]>([])
  /** null ＝ 不扮演 */
  const [myRole, setMyRole] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 打开时重置全部状态，并按需补拉目录
  useEffect(() => {
    if (!open) return
    setStep('entry')
    setKeyword('')
    setDirectAgentId(null)
    setTitle('')
    setTemplate(null)
    setExtraIds([])
    setMyRole(null)
    setSubmitting(false)
    setError(null)
    if (!catalogLoaded) fetchCatalog()
  }, [open, catalogLoaded, fetchCatalog])

  // Esc 关闭
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  /** 可对话的 Agent（排除检索类工具 Agent） */
  const chatAgents = useMemo(() => agents.filter((a) => !a.is_tool), [agents])

  const filteredAgents = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return chatAgents
    return chatAgents.filter((a) =>
      `${a.name}${a.role_label || ''}${a.description || ''}`.toLowerCase().includes(kw),
    )
  }, [chatAgents, keyword])

  /** 群聊最终成员：模板 roster（含自动补 host） + 用户追加 */
  const roster = useMemo<RosterEntry[]>(() => {
    if (!template) return []
    const list: RosterEntry[] = (template.roster_summary || []).map((r) => ({
      agent_id: r.agent_id,
      name: r.name,
      role_label: r.role_label ?? undefined,
      is_tool: r.is_tool,
      role: r.agent_id === template.host_agent_id ? 'host' : 'member',
      extra: false,
    }))
    const seen = new Set(list.map((r) => r.agent_id))
    if (template.host_agent_id && !seen.has(template.host_agent_id)) {
      const a = agents.find((x) => x.agent_id === template.host_agent_id)
      list.unshift({
        agent_id: template.host_agent_id,
        name: a?.name,
        role_label: a?.role_label ?? undefined,
        is_tool: a?.is_tool,
        role: 'host',
        extra: false,
      })
      seen.add(template.host_agent_id)
    }
    for (const id of extraIds) {
      if (seen.has(id)) continue
      seen.add(id)
      const a = agents.find((x) => x.agent_id === id)
      list.push({
        agent_id: id,
        name: a?.name,
        role_label: a?.role_label ?? undefined,
        is_tool: a?.is_tool,
        role: 'member',
        extra: true,
      })
    }
    return list
  }, [template, extraIds, agents])

  const rosterIds = useMemo(() => new Set(roster.map((r) => r.agent_id)), [roster])
  const addableAgents = useMemo(
    () => chatAgents.filter((a) => !rosterIds.has(a.agent_id)),
    [chatAgents, rosterIds],
  )

  if (!open) return null

  function finish(conv: Conversation) {
    upsertConversation(conv)
    selectConversation(conv.id)
    onClose()
  }

  async function handleSubmit() {
    setError(null)
    if (step === 'direct') {
      if (!directAgentId) return
      setSubmitting(true)
      try {
        const conv = await createConversation({
          type: 'direct',
          target_agent_id: directAgentId,
          title: title.trim() || undefined,
        })
        finish(conv)
      } catch (e) {
        setError(errText(e))
        setSubmitting(false)
      }
      return
    }
    if (step === 'roster') {
      if (!template) return
      setSubmitting(true)
      try {
        const conv = await createConversation({
          type: 'group',
          template_id: template.case_type,
          title: title.trim() || undefined,
          agent_ids: extraIds,
          my_role: myRole || undefined,
        })
        finish(conv)
      } catch (e) {
        setError(errText(e))
        setSubmitting(false)
      }
    }
  }

  function goBack() {
    setError(null)
    if (step === 'direct' || step === 'template') setStep('entry')
    else if (step === 'roster') setStep('template')
  }

  const footerBtn = 'h-9 px-4 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg mx-4 bg-white rounded-2xl shadow-xl flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <header className="h-14 px-5 flex items-center justify-between border-b border-slate-200 flex-shrink-0">
          <div className="flex items-center gap-2">
            {step !== 'entry' && (
              <button
                onClick={goBack}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 transition-colors"
                title="返回"
              >
                <ArrowLeft size={17} />
              </button>
            )}
            <h2 className="text-sm font-semibold text-slate-800">
              {step === 'entry' && '新建会话'}
              {step === 'direct' && '智能咨询 · 选择 Agent'}
              {step === 'template' && '模拟法庭 · 选择案情模板'}
              {step === 'roster' && '模拟法庭 · 确认成员'}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X size={18} />
          </button>
        </header>

        {/* 主体 */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {step === 'entry' && (
            <div className="space-y-3">
              <button
                onClick={() => setStep('direct')}
                className="w-full flex items-start gap-4 p-4 rounded-xl border border-slate-200 hover:border-blue-400 hover:bg-blue-50/40 transition-colors text-left"
              >
                <div className="w-11 h-11 rounded-xl bg-slate-100 text-slate-600 flex items-center justify-center flex-shrink-0">
                  <User size={20} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800">单聊 · 智能咨询</p>
                  <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                    与某一位律师 / 顾问一对一对话，例如单独咨询原告律师。
                  </p>
                </div>
              </button>

              <button
                onClick={() => setStep('template')}
                className="w-full flex items-start gap-4 p-4 rounded-xl border border-slate-200 hover:border-blue-400 hover:bg-blue-50/40 transition-colors text-left"
              >
                <div className="w-11 h-11 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center flex-shrink-0">
                  <Users size={20} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800">群聊 · 模拟法庭 / 会商</p>
                  <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                    从案情模板接入多 Agent，可扮演其中任意角色，也可完全不扮演。
                  </p>
                </div>
              </button>
            </div>
          )}

          {step === 'direct' && (
            <div>
              <div className="relative mb-3">
                <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="搜索 Agent"
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
                />
              </div>

              <div className="space-y-1.5">
                {filteredAgents.map((a) => {
                  const active = a.agent_id === directAgentId
                  return (
                    <button
                      key={a.agent_id}
                      onClick={() => setDirectAgentId(a.agent_id)}
                      className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-colors text-left ${
                        active
                          ? 'border-blue-500 bg-blue-50/60'
                          : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <Avatar name={a.name} avatar={a.avatar} seed={a.agent_id} size={36} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-slate-800 truncate">{a.name}</span>
                          {a.role_label && (
                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-500 flex-shrink-0">
                              {a.role_label}
                            </span>
                          )}
                        </div>
                        {a.description && (
                          <p className="text-[11px] text-slate-400 mt-0.5 truncate">{a.description}</p>
                        )}
                      </div>
                      {active && <Check size={18} className="text-blue-600 flex-shrink-0" />}
                    </button>
                  )
                })}
                {filteredAgents.length === 0 && (
                  <p className="text-center text-xs text-slate-400 py-6">没有匹配的 Agent</p>
                )}
              </div>
            </div>
          )}

          {step === 'template' && (
            <div className="space-y-2">
              {templates.filter((t) => t.enabled !== false).map((t) => {
                const active = template?.case_type === t.case_type
                const count = (t.roster_summary || []).length
                return (
                  <button
                    key={t.case_type}
                    onClick={() => {
                      setTemplate(t)
                      setExtraIds([])
                      setMyRole(null)
                    }}
                    className={`w-full flex items-start gap-3 p-3.5 rounded-xl border transition-colors text-left ${
                      active
                        ? 'border-blue-500 bg-blue-50/60'
                        : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                    }`}
                  >
                    <div className="w-10 h-10 rounded-lg bg-blue-100 text-blue-600 flex items-center justify-center flex-shrink-0">
                      <MessagesSquare size={18} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-800">{t.name}</span>
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-500 flex-shrink-0">
                          {count} 位成员
                        </span>
                      </div>
                      {t.description && (
                        <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">{t.description}</p>
                      )}
                    </div>
                    {active && <Check size={18} className="text-blue-600 flex-shrink-0 mt-1" />}
                  </button>
                )
              })}
              {templates.length === 0 && (
                <p className="text-center text-xs text-slate-400 py-6">模板加载中或暂无可用模板</p>
              )}
            </div>
          )}

          {step === 'roster' && template && (
            <div className="space-y-5">
              <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-100">
                <p className="text-sm font-semibold text-slate-800">{template.name}</p>
                {template.description && (
                  <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">{template.description}</p>
                )}
              </div>

              {/* 参与成员 */}
              <div>
                <p className="text-xs font-medium text-slate-500 mb-2">
                  参与成员（{roster.length}）
                </p>
                <div className="space-y-1.5">
                  {roster.map((m) => (
                    <div
                      key={m.agent_id}
                      className="flex items-center gap-3 px-3 py-2 rounded-lg bg-white border border-slate-100"
                    >
                      <Avatar name={m.name || m.agent_id} avatar={null} seed={m.agent_id} size={30} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm text-slate-700 truncate">{m.name || m.agent_id}</span>
                          {m.is_tool && (
                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-400 flex-shrink-0">
                              工具
                            </span>
                          )}
                        </div>
                        {m.role_label && (
                          <p className="text-[11px] text-slate-400 truncate">{m.role_label}</p>
                        )}
                      </div>
                      {m.extra && (
                        <button
                          onClick={() => setExtraIds((ids) => ids.filter((id) => id !== m.agent_id))}
                          className="text-[11px] text-slate-400 hover:text-red-500 transition-colors flex-shrink-0"
                        >
                          移除
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* 追加 Agent */}
              {addableAgents.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-500 mb-2">追加 Agent（可选）</p>
                  <div className="flex flex-wrap gap-2">
                    {addableAgents.map((a) => (
                      <button
                        key={a.agent_id}
                        onClick={() => setExtraIds((ids) => [...ids, a.agent_id])}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-200 text-xs text-slate-600 hover:border-blue-400 hover:text-blue-600 hover:bg-blue-50/40 transition-colors"
                        title={a.description || a.name}
                      >
                        <Plus size={12} />
                        {a.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 我扮演 */}
              <div>
                <p className="text-xs font-medium text-slate-500 mb-2">我扮演的角色</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => setMyRole(null)}
                    className={`px-3 py-1.5 rounded-lg border text-xs transition-colors ${
                      myRole === null
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                    }`}
                  >
                    我不扮演（全 AI）
                  </button>
                  {roster.map((m) => (
                    <button
                      key={m.agent_id}
                      onClick={() => setMyRole(m.agent_id)}
                      className={`px-3 py-1.5 rounded-lg border text-xs transition-colors ${
                        myRole === m.agent_id
                          ? 'border-blue-500 bg-blue-50 text-blue-700'
                          : 'border-slate-200 text-slate-600 hover:border-slate-300'
                      }`}
                    >
                      {m.name || m.agent_id}
                    </button>
                  ))}
                </div>
                <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">
                  扮演后，轮到该角色发言时先由你发言，可用「交还给 AI」让它继续说。
                </p>
              </div>

              {/* 标题 */}
              <div>
                <p className="text-xs font-medium text-slate-500 mb-2">会话标题（可选）</p>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={template.name}
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
                />
              </div>
            </div>
          )}

          {error && (
            <div className="mt-4 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        {/* 底部 */}
        {step !== 'entry' && (
          <footer className="px-5 py-3 border-t border-slate-200 flex items-center justify-end gap-2 flex-shrink-0">
            <button onClick={goBack} className={`${footerBtn} text-slate-600 hover:bg-slate-100`}>
              返回
            </button>

            {step === 'direct' && (
              <button
                onClick={handleSubmit}
                disabled={!directAgentId || submitting}
                className={`${footerBtn} bg-blue-600 text-white hover:bg-blue-700 flex items-center gap-1.5`}
              >
                {submitting && <Loader2 size={14} className="animate-spin" />}
                开始单聊
              </button>
            )}

            {step === 'template' && (
              <button
                onClick={() => setStep('roster')}
                disabled={!template}
                className={`${footerBtn} bg-blue-600 text-white hover:bg-blue-700`}
              >
                下一步
              </button>
            )}

            {step === 'roster' && (
              <button
                onClick={handleSubmit}
                disabled={submitting || roster.length === 0}
                className={`${footerBtn} bg-blue-600 text-white hover:bg-blue-700 flex items-center gap-1.5`}
              >
                {submitting && <Loader2 size={14} className="animate-spin" />}
                创建群聊
              </button>
            )}
          </footer>
        )}
      </div>
    </div>
  )
}
