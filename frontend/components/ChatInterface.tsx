'use client'

import { useState, useRef, useEffect, useMemo } from 'react'
import {
  Send, Paperclip, Plus, Clock, User, Sparkles, Copy, Check,
  Trash2, MessageSquare, X, StopCircle, RefreshCw, FileText,
  Lightbulb, AlertTriangle, BookOpen, HelpCircle, ChevronRight,
  Scale
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useChatStore } from '@/store/useChatStore'

const QUICK_QUESTIONS = [
  { icon: '🏠', title: '房东不退押金该怎么维权？', desc: '租房合同纠纷', color: 'text-blue-400' },
  { icon: '👤', title: '朋友借钱一直不还该怎么办？', desc: '民间借贷纠纷', color: 'text-purple-400' },
  { icon: '🛒', title: '网购商品有质量问题能退吗？', desc: '消费者权益保护', color: 'text-emerald-400' },
  { icon: '�', title: '劳动合同到期不续签有补偿吗？', desc: '劳动纠纷处理', color: 'text-amber-400' },
]

const QUICK_TAGS = [
  { label: '常见法规', icon: BookOpen },
  { label: '风险提示', icon: AlertTriangle },
  { label: '相关法理', icon: Scale },
  { label: '案例参考', icon: FileText },
  { label: '生成文书', icon: Sparkles },
]

interface ParsedContent {
  summary?: string
  judgment?: string[]
  materials?: string[]
  actions?: string[]
  laws?: string[]
  risks?: string
}

function parseStructured(content: string): ParsedContent | null {
  if (!content) return null
  const r: ParsedContent = {}
  const s = content.match(/根据您的描述[^\n]*\n?([\s\S]*?)(?=初步判断|建议收集|可采取行动|$)/)
  if (s) r.summary = s[1].trim()
  const j = content.match(/初步判断[\s\S]*?(?=建议收集材料|可采取行动|相关法条|风险提示|$)/)
  if (j) { const items = j[0].match(/[-•·]\s*.+/g); if (items) r.judgment = items.map(x => x.replace(/^[-•·]\s*/, '')) }
  const m = content.match(/建议收集材料[\s\S]*?(?=可采取行动|相关法条|风险提示|免责声明|$)/)
  if (m) { const items = m[0].match(/[-•·]\s*.+/g); if (items) r.materials = items.map(x => x.replace(/^[-•·]\s*/, '')) }
  const a = content.match(/可采取行动[\s\S]*?(?=相关法条|风险提示|免责声明|注：|$)/)
  if (a) { const items = a[0].match(/[-•·]\s*.+/g); if (items) r.actions = items.map(x => x.replace(/^[-•·]\s*/, '')) }
  return (r.summary || r.judgment?.length || r.materials?.length || r.actions?.length) ? r : null
}

function StructuredReply({ content, isStreaming }: { content: string; isStreaming: boolean }) {
  const parsed = parseStructured(content)
  const [copied, setCopied] = useState(false)

  if (!parsed && !isStreaming) return (
    <div className="glass-card-static rounded-2xl rounded-tl-sm overflow-hidden">
      <div className="p-4 text-xs text-gold-200/75 leading-relaxed whitespace-pre-wrap">{content}</div>
    </div>
  )

  return (
    <div className="glass-card-static rounded-2xl rounded-tl-sm overflow-hidden">
      <div className="p-4 space-y-3">
        {parsed?.summary && <p className="text-xs text-gold-200/80 leading-relaxed">{parsed.summary}</p>}

        {parsed?.judgment && parsed.judgment.length > 0 && (
          <div className="border-l-2 border-blue-400/50 pl-3 space-y-1.5">
            <div className="flex items-center gap-2 mb-1"><Sparkles size={13} className="text-blue-400" /><span className="text-[11px] font-semibold text-blue-300">初步判断</span></div>
            <ul className="space-y-1 ml-5 list-disc">
              {parsed.judgment.map((item, i) => <li key={i} className="text-[11px] text-gold-200/65 leading-relaxed">{item}</li>)}
            </ul>
          </div>
        )}

        {parsed?.materials && parsed.materials.length > 0 && (
          <div className="border-l-2 border-emerald-400/50 pl-3 space-y-1.5">
            <div className="flex items-center gap-2 mb-1"><Paperclip size={13} className="text-emerald-400" /><span className="text-[11px] font-semibold text-emerald-300">建议补充材料</span></div>
            <ul className="space-y-1 ml-5 list-disc">
              {parsed.materials.map((item, i) => <li key={i} className="text-[11px] text-gold-200/65 leading-relaxed">{item}</li>)}
            </ul>
          </div>
        )}

        {parsed?.actions && parsed.actions.length > 0 && (
          <div className="border-l-2 border-orange-400/50 pl-3 space-y-1.5">
            <div className="flex items-center gap-2 mb-1"><Send size={13} className="text-orange-400" /><span className="text-[11px] font-semibold text-orange-350">可采取行动</span></div>
            <ul className="space-y-1 ml-5 list-disc">
              {parsed.actions.map((item, i) => <li key={i} className="text-[11px] text-gold-200/65 leading-relaxed">{item}</li>)}
            </ul>
          </div>
        )}

        {isStreaming && (
          <div className="flex items-center gap-2 pt-1">
            <div className="flex gap-1">
              {[0,150,300].map(d => <span key={d} className="w-1 h-1 bg-blue-400 rounded-full animate-pulse" style={{animationDelay: `${d}ms`}} />)}
            </div>
            <span className="text-[10px] text-gold-200/35">正在分析法律依据...</span>
          </div>
        )}
      </div>

      {content && !isStreaming && (
        <div className="px-4 py-2 border-t border-white/5 flex items-center gap-3">
          <button onClick={() => { navigator.clipboard.writeText(content); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
            className="flex items-center gap-1 text-[10px] text-gold-200/40 hover:text-gold-200/70 transition-colors">
            {copied ? <Check size={11} /> : <Copy size={11} />} {copied ? '已复制' : '复制'}
          </button>
          <button onClick={() => { navigator.clipboard.writeText(content) }} className="flex items-center gap-1 text-[10px] text-gold-200/40 hover:text-gold-200/70 transition-colors">
            <MessageSquare size={11} /> 引用回复
          </button>
        </div>
      )}
    </div>
  )
}

export default function ChatInterface() {
  const {
    messages, isStreaming, authed, error, sendMessage, stopStreaming,
    checkAuth, sessions, currentSessionId, createSession, switchSession, deleteSession,
    uploadAndAnalyze,
  } = useChatStore()

  const [input, setInput] = useState('')
  const [attachedFiles, setAttachedFiles] = useState<File[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [quoteText, setQuoteText] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { checkAuth() }, [checkAuth])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, isStreaming])
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 128) + 'px'
    }
  }, [input])

  const handleSend = async () => {
    if ((!input.trim() && attachedFiles.length === 0) || isStreaming) return
    const msg = quoteText ? `${quoteText}\n\n${input}` : input.trim()
    setInput(''); setQuoteText('')
    await sendMessage(msg)

    // 如果有附件，上传并分析
    if (attachedFiles.length > 0) {
      for (const file of attachedFiles) {
        try {
          await uploadAndAnalyze(file)
        } catch (e) {
          console.error('附件上传失败:', e)
        }
      }
      setAttachedFiles([])
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }

  const sortedSessions = useMemo(() =>
    [...sessions].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()),
    [sessions],
  )
  const lastAssistantMsg = messages.filter(m => m.role === 'assistant').pop()

  return (
    <main className="flex-1 flex flex-col min-h-0 bg-[#0a1628] overflow-hidden">
      {/* 顶部栏 */}
      <header className="h-14 border-b border-white/5 flex items-center justify-between px-6 bg-[#0d1a2d]/80 backdrop-blur-sm flex-shrink-0 z-10">
        <div className="flex items-center gap-3">
          <MessageSquare size={20} className="text-blue-400" />
          <div>
            <h1 className="text-base font-semibold text-gold-200">智能法律咨询</h1>
            <p className="text-[10px] text-gold-200/35 -mt-0.5">适用于民事场景咨询、法律条文查询、风险识别判断</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => createSession()} className="gold-btn-sm flex items-center gap-1.5"><Plus size={12} /> 新建对话</button>
          <button onClick={() => setShowHistory(!showHistory)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs transition-all ${showHistory ? 'border-blue-400/30 bg-blue-500/10 text-blue-400' : 'border-white/10 text-gold-200/60 hover:bg-white/[0.03]'}`}>
            <Clock size={12} /> 历史记录
          </button>
        </div>
      </header>

      {/* 主内容区 */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 relative">

        {/* 历史会话弹窗 */}
        <AnimatePresence>
          {showHistory && (
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
              className="glass-card-static p-4 mb-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-medium text-gold-200/80">历史会话</h3>
                <button onClick={() => setShowHistory(false)} className="text-gold-200/40 hover:text-gold-200/70"><X size={14} /></button>
              </div>
              {sortedSessions.length === 0 ? (
                <p className="text-[11px] text-gold-200/30 text-center py-4">暂无历史会话</p>
              ) : (
                <div className="space-y-1 max-h-56 overflow-y-auto">
                  {sortedSessions.map(session => (
                    <div key={session.id}
                      className={`flex items-center gap-3 p-2.5 rounded-lg cursor-pointer transition-all group ${session.id === currentSessionId ? 'bg-blue-500/10 border border-blue-400/25' : 'hover:bg-white/[0.02]'}`}
                      onClick={() => { switchSession(session.id); setShowHistory(false) }}>
                      <MessageSquare size={13} className={session.id === currentSessionId ? 'text-blue-400' : 'text-gold-200/30'} />
                      <div className="flex-1 min-w-0">
                        <p className={`text-[11px] truncate ${session.id === currentSessionId ? 'text-blue-300 font-medium' : 'text-gold-200/60'}`}>{session.title}</p>
                        <p className="text-[9px] text-gold-200/25">{new Date(session.updatedAt).toLocaleDateString('zh-CN')} · {session.messages.length}条消息</p>
                      </div>
                      <button onClick={e => { e.stopPropagation(); deleteSession(session.id) }} className="opacity-0 group-hover:opacity-100 p-1 text-gold-200/30 hover:text-red-400 transition-all"><Trash2 size={11} /></button>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* 快捷问题卡片 */}
        {messages.length === 0 && !showHistory && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mb-4">
            <div className="flex items-center gap-2 mb-3">
              <Lightbulb size={14} className="text-gold-200/50" />
              <span className="text-xs font-medium text-gold-200/55">不知道怎么问？试试这些问题</span>
              <RefreshCw size={12} className="text-gold-200/25 cursor-pointer hover:text-gold-200/50" />
            </div>
            <div className="grid grid-cols-4 gap-3">
              {QUICK_QUESTIONS.map((q, i) => (
                <motion.button key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                  onClick={() => { setInput(q.title); setTimeout(() => handleSend(), 100) }}
                  className="flex flex-col items-start p-4 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:border-blue-400/25 hover:bg-blue-500/[0.03] transition-all text-left group">
                  <span className="text-xl mb-1.5">{q.icon}</span>
                  <span className={`text-[11px] ${q.color} font-medium leading-snug line-clamp-2 group-hover:text-blue-300`}>{q.title}</span>
                  <span className="text-[9px] text-gold-200/30 mt-1">{q.desc}</span>
                </motion.button>
              ))}
            </div>
          </motion.div>
        )}

        {/* 消息列表 */}
        <AnimatePresence mode="popLayout">
          {messages.map(msg => (
            <motion.div key={msg.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} gap-3`}>
              {msg.role === 'assistant' && (
                <div className="w-8 h-8 rounded-full bg-blue-500/15 border border-blue-400/25 flex items-center justify-center flex-shrink-0 mt-1">
                  <Sparkles size={14} className="text-blue-400" />
                </div>
              )}
              <div className={`max-w-[72%] ${msg.role === 'user' ? 'order-first' : ''}`}>
                {msg.role === 'user' ? (
                  <div className="bg-blue-600/90 text-white px-4 py-2.5 rounded-2xl rounded-tr-sm">
                    <p className="text-[11px] leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                    <span className="text-[9px] text-blue-200/60 mt-1 block text-right">{msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                ) : (
                  <StructuredReply content={msg.content} isStreaming={isStreaming && msg.id === lastAssistantMsg?.id} />
                )}
              </div>
              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-full bg-gold-400/10 border border-gold-400/20 flex items-center justify-center flex-shrink-0 mt-1">
                  <User size={13} className="text-gold-300" />
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {/* 流式加载指示 */}
        {isStreaming && (!lastAssistantMsg || lastAssistantMsg.content) && (
          <div className="flex justify-start gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-500/15 border border-blue-400/25 flex items-center justify-center flex-shrink-0">
              <Sparkles size={14} className="text-blue-400 animate-pulse" />
            </div>
            <div className="glass-card-static px-4 py-2.5 rounded-2xl rounded-tl-sm">
              <div className="flex items-center gap-2">
                {[0,120,240].map(d => <span key={d} className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }} />)}
                <span className="text-[10px] text-gold-200/35">AI 正在分析...</span>
              </div>
            </div>
          </div>
        )}

        {/* 错误提示 */}
        {error && (
          <div className="flex justify-center"><div className="bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-2 max-w-md"><p className="text-[10px] text-red-400">{error}</p></div></div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 附件预览栏 */}
      {attachedFiles.length > 0 && (
        <div className="px-6 py-2 flex flex-wrap gap-2 border-t border-white/5 bg-white/[0.01]">
          {attachedFiles.map((f, i) => (
            <span key={i} className="flex items-center gap-1.5 text-[10px] bg-white/[0.04] text-gold-200/60 px-2.5 py-1 rounded-full border border-white/8">
              📎 {f.name}<button onClick={() => setAttachedFiles(prev => prev.filter((_, idx) => idx !== i))} className="text-gold-200/35 hover:text-red-400"><X size={9} /></button>
            </span>
          ))}
        </div>
      )}

      {/* 引用文本栏 */}
      {quoteText && (
        <div className="px-6 py-2 border-t border-white/5 bg-blue-500/[0.03]">
          <div className="flex items-start gap-2">
            <div className="w-0.5 h-7 bg-blue-400/50 rounded-full flex-shrink-0 mt-0.5" />
            <p className="text-[10px] text-gold-200/45 flex-1 line-clamp-2">{quoteText}</p>
            <button onClick={() => setQuoteText('')} className="text-gold-200/35 hover:text-gold-200/60 flex-shrink-0"><X size={12} /></button>
          </div>
        </div>
      )}

      {/* 输入区域 */}
      <div className="p-4 border-t border-white/5 bg-[#0c1729]/80 flex-shrink-0">
        <div className="max-w-4xl mx-auto">
          <div className="relative flex items-end gap-2.5">
            <button onClick={() => fileInputRef.current?.click()}
              className="p-2.5 rounded-xl border border-white/10 text-gold-200/40 hover:text-blue-400 hover:border-blue-400/30 transition-all">
              <Paperclip size={17} />
            </button>
            <input type="file" ref={fileInputRef} className="hidden" multiple accept=".pdf,.docx,.doc,.txt"
              onChange={(e) => { const fl = e.target.files; if (fl && fl.length) setAttachedFiles(prev => [...prev, ...Array.from(fl)]) } } />

            <div className="flex-1 relative">
              <textarea ref={textareaRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown}
                placeholder={quoteText ? '针对引用内容追问...' : '请输入您的法律问题，AI 为您提供专业诊断...'}
                rows={1} disabled={!authed || isStreaming}
                className={`w-full bg-white/[0.03] border rounded-xl px-4 py-3 pr-24 text-xs text-gold-200/85 placeholder:text-gold-200/25 focus:outline-none focus:border-blue-400/40 focus:ring-1 focus:ring-blue-400/10 resize-none min-h-[44px] max-h-28 transition-all disabled:opacity-40 ${
                  quoteText ? 'border-blue-400/30 focus:border-blue-400/50' : 'border-white/8'
                }`} />
              <div className="absolute right-3 bottom-2 flex items-center gap-2">
                <span className="text-[9px] text-gold-200/25">{input.length}/2000</span>
                {isStreaming ? (
                  <button onClick={stopStreaming} className="p-1.5 rounded-lg bg-red-500/15 border border-red-400/25 text-red-400 hover:bg-red-500/25 transition-all">
                    <StopCircle size={14} />
                  </button>
                ) : (
                  <button onClick={handleSend} disabled={(!input.trim() && attachedFiles.length === 0) || !authed}
                    className="p-1.5 rounded-lg bg-blue-500 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-blue-600 transition-all">
                    <Send size={14} />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* 快捷标签 */}
          <div className="flex items-center gap-2 mt-2.5 flex-wrap">
            {QUICK_TAGS.map((tag, i) => (
              <button key={i} onClick={() => setInput(tag.label)}
                className="flex items-center gap-1 px-2.5 py-1 rounded-full border border-white/8 text-[10px] text-gold-200/45 hover:text-blue-400 hover:border-blue-400/25 hover:bg-blue-500/[0.04] transition-all">
                <tag.icon size={10} />{tag.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </main>
  )
}
