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
  { icon: '🏠', title: '房东不退押金该怎么维权？', desc: '租房合同纠纷', color: 'text-gold-300' },
  { icon: '👤', title: '朋友借钱一直不还该怎么办？', desc: '民间借贷纠纷', color: 'text-gold-300' },
  { icon: '🛒', title: '网购商品有质量问题能退吗？', desc: '消费者权益保护', color: 'text-gold-300' },
  { icon: '💼', title: '劳动合同到期不续签有补偿吗？', desc: '劳动纠纷处理', color: 'text-gold-300' },
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
      <div className="p-4 text-xs text-slate-300 leading-relaxed whitespace-pre-wrap font-body">{content}</div>
    </div>
  )

  return (
    <div className="glass-card-static rounded-2xl rounded-tl-sm overflow-hidden">
      <div className="p-4 space-y-3">
        {parsed?.summary && <p className="text-xs text-slate-300 leading-relaxed font-body">{parsed.summary}</p>}

        {parsed?.judgment && parsed.judgment.length > 0 && (
          <div className="border-l-2 border-gold-400 pl-3 space-y-1.5">
            <div className="flex items-center gap-2 mb-1"><Sparkles size={13} className="text-gold-300" /><span className="text-[11px] font-semibold text-gold-300 font-body">初步判断</span></div>
            <ul className="space-y-1 ml-5 list-disc">
              {parsed.judgment.map((item, i) => <li key={i} className="text-[11px] text-slate-300 leading-relaxed font-body">{item}</li>)}
            </ul>
          </div>
        )}

        {parsed?.materials && parsed.materials.length > 0 && (
          <div className="border-l-2 border-emerald-400 pl-3 space-y-1.5">
            <div className="flex items-center gap-2 mb-1"><Paperclip size={13} className="text-emerald-400" /><span className="text-[11px] font-semibold text-emerald-400 font-body">建议补充材料</span></div>
            <ul className="space-y-1 ml-5 list-disc">
              {parsed.materials.map((item, i) => <li key={i} className="text-[11px] text-slate-300 leading-relaxed font-body">{item}</li>)}
            </ul>
          </div>
        )}

        {parsed?.actions && parsed.actions.length > 0 && (
          <div className="border-l-2 border-orange-400 pl-3 space-y-1.5">
            <div className="flex items-center gap-2 mb-1"><Send size={13} className="text-orange-400" /><span className="text-[11px] font-semibold text-orange-400 font-body">可采取行动</span></div>
            <ul className="space-y-1 ml-5 list-disc">
              {parsed.actions.map((item, i) => <li key={i} className="text-[11px] text-slate-300 leading-relaxed font-body">{item}</li>)}
            </ul>
          </div>
        )}

        {isStreaming && (
          <div className="flex items-center gap-2 pt-1">
            <div className="flex gap-1">
              {[0,150,300].map(d => <span key={d} className="w-1 h-1 bg-gold-400 rounded-full animate-pulse" style={{animationDelay: `${d}ms`}} />)}
            </div>
            <span className="text-[10px] text-slate-400 font-body">正在分析法律依据...</span>
          </div>
        )}
      </div>

      {content && !isStreaming && (
        <div className="px-4 py-2 border-t border-navy-700/30 flex items-center gap-3">
          <button onClick={() => { navigator.clipboard.writeText(content); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
            className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-gold-300 transition-colors font-body">
            {copied ? <Check size={11} /> : <Copy size={11} />} {copied ? '已复制' : '复制'}
          </button>
          <button onClick={() => { navigator.clipboard.writeText(content) }} className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-gold-300 transition-colors font-body">
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
    <main className="flex-1 flex flex-col min-h-0 bg-navy-950 overflow-hidden">
      {/* 顶部栏 */}
      <header className="h-14 border-b border-navy-700/30 flex items-center justify-between px-6 bg-navy-900/80 backdrop-blur-md flex-shrink-0 z-10">
        <div className="flex items-center gap-3">
          <MessageSquare size={20} className="text-gold-300" />
          <div>
            <h1 className="text-base font-semibold text-slate-50 font-body">智能法律咨询</h1>
            <p className="text-[10px] text-slate-400 -mt-0.5 font-body">适用于民事场景咨询、法律条文查询、风险识别判断</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => createSession()} className="gold-btn-sm flex items-center gap-1.5"><Plus size={12} /> 新建对话</button>
          <button onClick={() => setShowHistory(!showHistory)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs transition-all font-body ${showHistory ? 'border-gold-400/40 bg-gold-400/10 text-gold-300' : 'border-navy-700/30 text-slate-400 hover:text-gold-300 hover:border-gold-400/30'}`}>
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
                <h3 className="text-xs font-medium text-slate-200 font-body">历史会话</h3>
                <button onClick={() => setShowHistory(false)} className="text-slate-400 hover:text-gold-300 transition-colors"><X size={14} /></button>
              </div>
              {sortedSessions.length === 0 ? (
                <p className="text-[11px] text-slate-400 text-center py-4 font-body">暂无历史会话</p>
              ) : (
                <div className="space-y-1 max-h-56 overflow-y-auto">
                  {sortedSessions.map(session => (
                    <div key={session.id}
                      className={`flex items-center gap-3 p-2.5 rounded-lg cursor-pointer transition-all group ${session.id === currentSessionId ? 'bg-navy-800/50 border border-gold-400/20' : 'hover:bg-navy-800/30'}`}
                      onClick={() => { switchSession(session.id); setShowHistory(false) }}>
                      <MessageSquare size={13} className={session.id === currentSessionId ? 'text-gold-300' : 'text-slate-400'} />
                      <div className="flex-1 min-w-0">
                        <p className={`text-[11px] truncate font-body ${session.id === currentSessionId ? 'text-gold-300 font-medium' : 'text-slate-300'}`}>{session.title}</p>
                        <p className="text-[9px] text-slate-400 font-body">{new Date(session.updatedAt).toLocaleDateString('zh-CN')} · {session.messages.length}条消息</p>
                      </div>
                      <button onClick={e => { e.stopPropagation(); deleteSession(session.id) }} className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-400 transition-all"><Trash2 size={11} /></button>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* 欢迎介绍 + 快捷问题卡片 */}
        {messages.length === 0 && !showHistory && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mb-4">
            {/* AI 固定欢迎介绍 */}
            <div className="flex justify-start gap-3 mb-5">
              <div className="w-8 h-8 rounded-full bg-navy-800/60 border border-gold-400/30 flex items-center justify-center flex-shrink-0 mt-1">
                <Sparkles size={14} className="text-gold-300" />
              </div>
              <div className="glass-card-static rounded-2xl rounded-tl-sm overflow-hidden max-w-[72%]">
                <div className="p-4 space-y-2">
                  <p className="text-xs font-semibold text-slate-50 font-body">你好，我是 LegalMind AI</p>
                  <p className="text-[11px] text-slate-300 leading-relaxed font-body">
                    我是一个专业的中国法律智能助手，可以为您提供法律分析、条文解读和操作建议。
                    请直接输入您的法律问题，我会立即为您解答。
                  </p>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    <span className="px-2 py-0.5 rounded-full bg-navy-800/50 text-[9px] text-gold-300 border border-navy-700/30 font-body">民事纠纷</span>
                    <span className="px-2 py-0.5 rounded-full bg-navy-800/50 text-[9px] text-gold-300 border border-navy-700/30 font-body">合同审查</span>
                    <span className="px-2 py-0.5 rounded-full bg-navy-800/50 text-[9px] text-gold-300 border border-navy-700/30 font-body">劳动维权</span>
                    <span className="px-2 py-0.5 rounded-full bg-navy-800/50 text-[9px] text-gold-300 border border-navy-700/30 font-body">消费维权</span>
                  </div>
                </div>
              </div>
            </div>
            {/* 快捷问题 */}
            <div className="flex items-center gap-2 mb-3">
              <Lightbulb size={14} className="text-slate-400" />
              <span className="text-xs font-medium text-slate-400 font-body">不知道怎么问？试试这些问题</span>
              <RefreshCw size={12} className="text-slate-400 cursor-pointer hover:text-gold-300 transition-colors" />
            </div>
            <div className="grid grid-cols-4 gap-3">
              {QUICK_QUESTIONS.map((q, i) => (
                <motion.button key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                  onClick={() => { setInput(q.title); setTimeout(() => handleSend(), 100) }}
                  className="glass-card flex flex-col items-start p-4 rounded-xl text-left group">
                  <div className="feature-glow" />
                  <span className="text-xl mb-1.5">{q.icon}</span>
                  <span className="text-[11px] text-slate-300 font-medium leading-snug line-clamp-2 group-hover:text-gold-300 transition-colors font-body">{q.title}</span>
                  <span className="text-[9px] text-slate-400 mt-1 font-body">{q.desc}</span>
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
                <div className="w-8 h-8 rounded-full bg-navy-800/60 border border-gold-400/30 flex items-center justify-center flex-shrink-0 mt-1">
                  <Sparkles size={14} className="text-gold-300" />
                </div>
              )}
              <div className={`max-w-[72%] ${msg.role === 'user' ? 'order-first' : ''}`}>
                {msg.role === 'user' ? (
                  <div className="chat-bubble-user px-4 py-2.5 rounded-2xl rounded-tr-sm">
                    <p className="text-[11px] leading-relaxed whitespace-pre-wrap font-body">{msg.content}</p>
                    <span className="text-[9px] text-slate-400 mt-1 block text-right font-body">{msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                ) : (
                  <StructuredReply content={msg.content} isStreaming={isStreaming && msg.id === lastAssistantMsg?.id} />
                )}
              </div>
              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-full bg-navy-600 border border-navy-700/30 flex items-center justify-center flex-shrink-0 mt-1">
                  <User size={13} className="text-gold-300" />
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {/* 流式加载指示 */}
        {isStreaming && (!lastAssistantMsg || lastAssistantMsg.content) && (
          <div className="flex justify-start gap-3">
            <div className="w-8 h-8 rounded-full bg-navy-800/60 border border-gold-400/30 flex items-center justify-center flex-shrink-0">
              <Sparkles size={14} className="text-gold-300 animate-pulse" />
            </div>
            <div className="glass-card-static px-4 py-2.5 rounded-2xl rounded-tl-sm">
              <div className="flex items-center gap-2">
                {[0,120,240].map(d => <span key={d} className="w-1.5 h-1.5 bg-gold-400 rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }} />)}
                <span className="text-[10px] text-slate-400 font-body">AI 正在分析...</span>
              </div>
            </div>
          </div>
        )}

        {/* 错误提示 */}
        {error && (
          <div className="flex justify-center"><div className="bg-red-900/30 border border-red-500/30 rounded-lg px-4 py-2 max-w-md"><p className="text-[10px] text-red-400 font-body">{error}</p></div></div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 附件预览栏 */}
      {attachedFiles.length > 0 && (
        <div className="px-6 py-2 flex flex-wrap gap-2 border-t border-navy-700/30 bg-navy-900/50">
          {attachedFiles.map((f, i) => (
            <span key={i} className="flex items-center gap-1.5 text-[10px] bg-navy-800/50 text-slate-300 px-2.5 py-1 rounded-full border border-navy-700/30 font-body">
              📎 {f.name}<button onClick={() => setAttachedFiles(prev => prev.filter((_, idx) => idx !== i))} className="text-slate-400 hover:text-red-400 transition-colors"><X size={9} /></button>
            </span>
          ))}
        </div>
      )}

      {/* 引用文本栏 */}
      {quoteText && (
        <div className="px-6 py-2 border-t border-navy-700/30 bg-navy-800/30">
          <div className="flex items-start gap-2">
            <div className="w-0.5 h-7 bg-gold-400 rounded-full flex-shrink-0 mt-0.5" />
            <p className="text-[10px] text-slate-400 flex-1 line-clamp-2 font-body">{quoteText}</p>
            <button onClick={() => setQuoteText('')} className="text-slate-400 hover:text-gold-300 flex-shrink-0 transition-colors"><X size={12} /></button>
          </div>
        </div>
      )}

      {/* 输入区域 */}
      <div className="p-4 border-t border-navy-700/30 bg-navy-900 flex-shrink-0">
        <div className="max-w-4xl mx-auto">
          <div className="relative flex items-end gap-2.5">
            <button onClick={() => fileInputRef.current?.click()}
              className="p-2.5 rounded-xl border border-navy-700/30 text-slate-400 hover:text-gold-300 hover:border-gold-400/30 transition-all">
              <Paperclip size={17} />
            </button>
            <input type="file" ref={fileInputRef} className="hidden" multiple accept=".pdf,.docx,.doc,.txt"
              onChange={(e) => { const fl = e.target.files; if (fl && fl.length) setAttachedFiles(prev => [...prev, ...Array.from(fl)]) } } />

            <div className="flex-1 relative">
              <textarea ref={textareaRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown}
                placeholder={quoteText ? '针对引用内容追问...' : '请输入您的法律问题，AI 为您提供专业诊断...'}
                rows={1} disabled={!authed || isStreaming}
                className={`input-field pr-24 text-xs resize-none min-h-[44px] max-h-28 disabled:opacity-40 ${
                  quoteText ? 'border-gold-400/30' : ''
                }`} />
              <div className="absolute right-3 bottom-2 flex items-center gap-2">
                <span className="text-[9px] text-slate-400 font-body">{input.length}/2000</span>
                {isStreaming ? (
                  <button onClick={stopStreaming} className="p-1.5 rounded-lg bg-red-900/30 border border-red-500/30 text-red-400 hover:bg-red-900/50 transition-all">
                    <StopCircle size={14} />
                  </button>
                ) : (
                  <button onClick={handleSend} disabled={(!input.trim() && attachedFiles.length === 0) || !authed}
                    className="gold-btn-sm p-1.5 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed">
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
                className="flex items-center gap-1 px-2.5 py-1 rounded-full border border-navy-700/30 text-[10px] text-slate-400 hover:text-gold-300 hover:border-gold-400/30 hover:bg-navy-800/50 transition-all font-body">
                <tag.icon size={10} />{tag.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </main>
  )
}
