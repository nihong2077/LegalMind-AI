'use client'

/**
 * 可折叠右栏（T1.8-M1 只读 → M4 群管理 + 本轮发言顺序）
 * - 群成员：呈现成员与扮演角标；群聊可追加 / 移除成员。
 * - 本轮发言顺序：当前轮次 checkpoint（已发言 / 是否提前结束），
 *   每条可「回到此轮」从该 checkpoint 分叉重跑。
 */
import { useEffect, useMemo, useState } from 'react'
import { FileText, History, Loader2, Plus, RotateCcw, X } from 'lucide-react'
import {
  CheckpointItem,
  addMember,
  forkTurn,
  listCheckpoints,
  removeMember,
} from '@/app/lib/collab'
import { useCollabStore } from '@/store/useCollabStore'
import { useCollabStreamStore } from '@/store/useCollabStreamStore'
import Avatar from './Avatar'

// 中性化文案映射：对外不展示「主持人/指令/理由」等身份化措辞
const DIRECTIVE_LABELS: Record<string, string> = {
  continue: '继续发言',
  ask_user: '请求补充信息',
  verdict: '作出判决',
  conclude: '结束会商',
}

const STOP_LABELS: Record<string, string> = {
  max_rounds: '达到轮次上限',
  budget: '达到调用上限',
  no_speaker: '无后续发言',
  user_conclude: '用户结束会商',
  direct_done: '本轮已完成',
  verdict: '作出判决',
  conclude: '结束会商',
}

export default function RightRail() {
  const conversations = useCollabStore((s) => s.conversations)
  const agents = useCollabStore((s) => s.agents)
  const selectedId = useCollabStore((s) => s.selectedId)
  const rightRailOpen = useCollabStore((s) => s.rightRailOpen)
  const selectConversation = useCollabStore((s) => s.selectConversation)
  const turnId = useCollabStreamStore((s) => s.turnId)
  const generateMinutes = useCollabStreamStore((s) => s.generateMinutes)

  const conversation = conversations.find((c) => c.id === selectedId) || null
  const isGroup = conversation?.type === 'group'

  const [checkpoints, setCheckpoints] = useState<CheckpointItem[]>([])
  const [cpLoading, setCpLoading] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [minutesBusy, setMinutesBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // 时间线：会话 / 轮次变化时拉取该轮 checkpoint 链
  useEffect(() => {
    setNotice(null)
    if (!conversation || !isGroup || !turnId) {
      setCheckpoints([])
      return
    }
    let alive = true
    setCpLoading(true)
    listCheckpoints(conversation.id, turnId)
      .then((res) => {
        if (alive) setCheckpoints(res.checkpoints || [])
      })
      .catch(() => {
        if (alive) setCheckpoints([])
      })
      .finally(() => {
        if (alive) setCpLoading(false)
      })
    return () => {
      alive = false
    }
  }, [conversation?.id, isGroup, turnId])

  const nameOf = useMemo(() => {
    const map = new Map<string, string>()
    conversation?.members.forEach((m) => map.set(m.agent_id, m.name || m.agent_id))
    agents.forEach((a) => {
      if (!map.has(a.agent_id)) map.set(a.agent_id, a.name)
    })
    return (id: string) => map.get(id) || id
  }, [conversation, agents])

  const memberIds = useMemo(
    () => new Set((conversation?.members || []).map((m) => m.agent_id)),
    [conversation],
  )
  const addableAgents = useMemo(
    () => agents.filter((a) => !a.is_tool && !memberIds.has(a.agent_id)),
    [agents, memberIds],
  )

  if (!rightRailOpen) return null

  async function refresh() {
    if (conversation) await selectConversation(conversation.id)
  }

  async function handleAdd(agentId: string) {
    if (!conversation || busy) return
    setBusy(agentId)
    setNotice(null)
    try {
      await addMember(conversation.id, agentId)
      await refresh()
      setAddOpen(false)
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '添加失败')
    } finally {
      setBusy(null)
    }
  }

  async function handleRemove(agentId: string) {
    if (!conversation || busy) return
    setBusy(agentId)
    setNotice(null)
    try {
      await removeMember(conversation.id, agentId)
      await refresh()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '移除失败')
    } finally {
      setBusy(null)
    }
  }

  async function handleFork(checkpointId: string) {
    if (!conversation || !turnId || busy) return
    setBusy(checkpointId)
    setNotice(null)
    try {
      await forkTurn(conversation.id, turnId, { checkpoint_id: checkpointId })
      setNotice('已从该检查点分叉重跑')
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '分叉失败')
    } finally {
      setBusy(null)
    }
  }

  async function handleMinutes() {
    if (!conversation || minutesBusy) return
    setMinutesBusy(true)
    setNotice(null)
    try {
      await generateMinutes()
      setNotice('已生成会商纪要')
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '生成会商纪要失败')
    } finally {
      setMinutesBusy(false)
    }
  }

  return (
    <aside className="w-[300px] h-screen bg-white border-l border-slate-200 flex flex-col flex-shrink-0">
      {!conversation ? (
        <div className="flex-1 flex items-center justify-center text-xs text-slate-400">
          未选择会话
        </div>
      ) : (
        <>
          <header className="h-14 px-4 flex items-center gap-2 border-b border-slate-200 flex-shrink-0">
            <History size={16} className="text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-800">会话信息</h3>
          </header>

          <div className="flex-1 overflow-y-auto">
            {notice && (
              <div className="mx-4 mt-3 px-3 py-2 rounded-lg bg-slate-50 border border-slate-200 text-[11px] text-slate-500">
                {notice}
              </div>
            )}

            <div className="px-4 py-3 border-b border-slate-100">
              <div className="flex items-center justify-between mb-2">
                <p className="text-[11px] text-slate-400">
                  {isGroup ? `群成员（${conversation.members.length}）` : '对话 Agent'}
                </p>
                {isGroup && (
                  <button
                    onClick={() => setAddOpen((v) => !v)}
                    className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-blue-600 hover:bg-blue-50 transition-colors"
                  >
                    <Plus size={12} />
                    添加
                  </button>
                )}
              </div>

              {isGroup && addOpen && (
                <div className="mb-2 p-2 rounded-lg border border-slate-200 bg-slate-50">
                  {addableAgents.length === 0 ? (
                    <p className="text-[11px] text-slate-400 px-1 py-1">没有可添加的 Agent</p>
                  ) : (
                    <div className="max-h-44 overflow-y-auto space-y-1">
                      {addableAgents.map((a) => (
                        <button
                          key={a.agent_id}
                          onClick={() => void handleAdd(a.agent_id)}
                          disabled={busy === a.agent_id}
                          className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white transition-colors text-left disabled:opacity-50"
                        >
                          <Avatar name={a.name} avatar={a.avatar} seed={a.agent_id} size={24} />
                          <span className="text-xs text-slate-700 truncate flex-1">{a.name}</span>
                          {busy === a.agent_id ? (
                            <Loader2 size={12} className="animate-spin text-blue-500" />
                          ) : (
                            <Plus size={12} className="text-blue-500" />
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="space-y-2 mt-1">
                {conversation.members.map((m) => {
                  const isMe = conversation.my_role === m.agent_id
                  const removable = isGroup && m.role !== 'host' && !isMe
                  return (
                    <div key={m.agent_id} className="flex items-center gap-3">
                      <Avatar
                        name={m.name || m.agent_id}
                        avatar={m.avatar}
                        seed={m.agent_id}
                        size={32}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm text-slate-700 truncate">
                            {m.name || m.agent_id}
                          </span>
                          {isMe && (
                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-blue-100 text-blue-600 flex-shrink-0">
                              你（扮演）
                            </span>
                          )}
                        </div>
                        {m.role_label && (
                          <p className="text-[11px] text-slate-400 truncate">{m.role_label}</p>
                        )}
                      </div>
                      {removable && (
                        <button
                          onClick={() => void handleRemove(m.agent_id)}
                          disabled={busy === m.agent_id}
                          className="w-6 h-6 flex items-center justify-center rounded text-slate-300 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-40"
                          title="移除成员"
                        >
                          {busy === m.agent_id ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <X size={13} />
                          )}
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>

            {isGroup && (
              <div className="px-4 py-3 border-b border-slate-100">
                <button
                  onClick={() => void handleMinutes()}
                  disabled={minutesBusy}
                  className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-slate-200 text-xs text-slate-600 hover:bg-slate-50 hover:text-blue-600 transition-colors disabled:opacity-50"
                >
                  {minutesBusy ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <FileText size={13} />
                  )}
                  生成会商纪要
                </button>
              </div>
            )}

            {isGroup && (
              <div className="px-4 py-4">
                <div className="flex items-center gap-2 text-slate-500 mb-3">
                  <History size={14} />
                  <span className="text-xs font-medium">本轮发言顺序</span>
                  {cpLoading && <Loader2 size={11} className="animate-spin text-slate-400" />}
                </div>

                {!turnId && (
                  <p className="text-[11px] text-slate-400 leading-relaxed">
                    发起一轮会商后，这里展示本轮的发言顺序与是否提前结束。
                  </p>
                )}

                {turnId && checkpoints.length === 0 && !cpLoading && (
                  <p className="text-[11px] text-slate-400">该轮次暂无发言记录。</p>
                )}

                <div className="space-y-2">
                  {checkpoints.map((cp) => (
                    <div
                      key={cp.checkpoint_id || `${cp.step}`}
                      className={`rounded-lg border p-2.5 ${
                        cp.is_latest ? 'border-blue-300 bg-blue-50/50' : 'border-slate-200'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-medium text-slate-600">
                          第 {cp.round} 轮 · 步骤 {cp.step}
                        </span>
                        {cp.is_latest && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-blue-100 text-blue-600 flex-shrink-0">
                            当前
                          </span>
                        )}
                      </div>

                      {cp.directive && DIRECTIVE_LABELS[cp.directive] && (
                        <p className="text-[11px] text-slate-600 mt-1">
                          <span className="text-slate-400">本轮：</span>
                          {DIRECTIVE_LABELS[cp.directive]}
                        </p>
                      )}
                      {cp.force_stop_reason && (
                        <p className="text-[11px] text-amber-600 mt-0.5">
                          <span className="text-amber-500">提前结束：</span>
                          {STOP_LABELS[cp.force_stop_reason] || '本轮结束'}
                        </p>
                      )}
                      {cp.spoken.length > 0 && (
                        <p className="text-[11px] text-slate-400 mt-1 truncate">
                          已发言：{cp.spoken.map((s) => nameOf(s)).join('、')}
                        </p>
                      )}

                      {!cp.is_latest && cp.checkpoint_id && (
                        <button
                          onClick={() => void handleFork(cp.checkpoint_id as string)}
                          disabled={busy === cp.checkpoint_id}
                          className="mt-2 flex items-center gap-1 px-2 py-1 rounded text-[11px] text-blue-600 hover:bg-blue-50 transition-colors disabled:opacity-40"
                        >
                          {busy === cp.checkpoint_id ? (
                            <Loader2 size={11} className="animate-spin" />
                          ) : (
                            <RotateCcw size={11} />
                          )}
                          回到此轮
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </aside>
  )
}
