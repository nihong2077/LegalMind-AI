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
import Disclaimer from '@/components/Disclaimer'

const QUICK_QUESTIONS = [
  { icon: '🏠', title: '房东不退押金该怎么维权？', desc: '租房合同纠纷', color: 'text-blue-600' },
  { icon: '👤', title: '朋友借钱一直不还该怎么办？', desc: '民间借贷纠纷', color: 'text-purple-600' },
  { icon: '🛒', title: '网购商品有质量问题能退吗？', desc: '消费者权益保护', color: 'text-emerald-600' },
  { icon: '💼', title: '劳动合同到期不续签有补偿吗？', desc: '劳动纠纷处理', color: 'text-amber-600' },
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
  const [copied, setCopied] = useState(false)

  // 流式过程中直接显示纯文本，避免正则解析不完整内容导致"一团一团"跳变
  if (isStreaming) return (
    <div className="glass-card-static rounded-2xl rounded-tl-sm overflow-hidden">
      <div className="p-5 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{content}</div>
      <div className="flex items-center gap-2 px-5 pb-3">
        <div className="flex gap-1">
          {[0,150,300].map(d => <span key={d} className="w-1.5 h-1.5 bg-blue-600 rounded-full animate-pulse" style={{animationDelay: `${d}ms`}} />)}
        </div>
        <span className="text-xs text-slate-400">正在生成回答...</span>
      </div>
    </div>
  )

  const parsed = parseStructured(content)

  if (!parsed) return (
    <div className="glass-card-static rounded-2xl rounded-tl-sm overflow-hidden">
      <div className="p-5 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{content}</div>
      <div className="px-5 py-2.5 border-t border-gray-200 flex items-center gap-3">
        <button onClick={() => { navigator.clipboard.writeText(content); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
          className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition-colors">
          {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? '已复制' : '复制'}
        </button>
      </div>
    </div>
  )

  return (
    <div className="glass-card-static rounded-2xl rounded-tl-sm overflow-hidden">
      <div className="p-5 space-y-4">
        {parsed?.summary && <p className="text-sm text-slate-700 leading-relaxed">{parsed.summary}</p>}

        {parsed?.judgment && parsed.judgment.length > 0 && (
          <div className="border-l-2 border-blue-500 pl-4 space-y-2">
            <div className="flex items-center gap-2 mb-1"><Sparkles size={15} className="text-blue-600" /><span className="text-sm font-semibold text-blue-600">初步判断</span></div>
            <ul className="space-y-1.5 ml-5 list-disc">
              {parsed.judgment.map((item, i) => <li key={i} className="text-sm text-slate-600 leading-relaxed">{item}</li>)}
            </ul>
          </div>
        )}

        {parsed?.materials && parsed.materials.length > 0 && (
          <div className="border-l-2 border-emerald-500 pl-4 space-y-2">
            <div className="flex items-center gap-2 mb-1"><Paperclip size={15} className="text-emerald-600" /><span className="text-sm font-semibold text-emerald-600">建议补充材料</span></div>
            <ul className="space-y-1.5 ml-5 list-disc">
              {parsed.materials.map((item, i) => <li key={i} className="text-sm text-slate-600 leading-relaxed">{item}</li>)}
            </ul>
          </div>
        )}

        {parsed?.actions && parsed.actions.length > 0 && (
          <div className="border-l-2 border-orange-500 pl-4 space-y-2">
            <div className="flex items-center gap-2 mb-1"><Send size={15} className="text-orange-600" /><span className="text-sm font-semibold text-orange-600">可采取行动</span></div>
            <ul className="space-y-1.5 ml-5 list-disc">
              {parsed.actions.map((item, i) => <li key={i} className="text-sm text-slate-600 leading-relaxed">{item}</li>)}
            </ul>
          </div>
        )}

      </div>

      <div className="px-5 py-2.5 border-t border-gray-200 flex items-center gap-3">
          <button onClick={() => { navigator.clipboard.writeText(content); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
            className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition-colors">
            {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? '已复制' : '复制'}
          </button>
          <button onClick={() => { navigator.clipboard.writeText(content) }} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition-colors">
            <MessageSquare size={13} /> 引用回复
          </button>
        </div>
    </div>
  )
}

export default function ChatInterface() {
  const {
    messages, isStreaming, streamingPhase, authed, error, sendMessage, stopStreaming,
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
    <main className="flex-1 flex flex-col min-h-0 bg-white overflow-hidden">
      {/* 顶部栏 */}
      <header className="h-16 border-b border-gray-200 flex items-center justify-between px-6 bg-white flex-shrink-0 z-10">
        <div className="flex items-center gap-3">
          <MessageSquare size={22} className="text-blue-600" />
          <div>
            <h1 className="text-base font-semibold text-slate-800">智能法律咨询</h1>
            <p className="text-xs text-slate-400 -mt-0.5">适用于民事场景咨询、法律条文查询、风险识别判断</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => createSession()} className="gold-btn-sm flex items-center gap-1.5"><Plus size={14} /> 新建对话</button>
          <button onClick={() => setShowHistory(!showHistory)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs transition-all ${showHistory ? 'border-blue-300 bg-blue-50 text-blue-600' : 'border-gray-200 text-slate-500 hover:bg-slate-50'}`}>
            <Clock size={14} /> 历史记录
          </button>
        </div>
      </header>

      {/* 主内容区 */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6 relative">

        {/* 历史会话弹窗 */}
        <AnimatePresence>
          {showHistory && (
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
              className="glass-card-static p-5 mb-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-slate-700">历史会话</h3>
                <button onClick={() => setShowHistory(false)} className="text-slate-400 hover:text-slate-600"><X size={16} /></button>
              </div>
              {sortedSessions.length === 0 ? (
                <p className="text-xs text-slate-400 text-center py-4">暂无历史会话</p>
              ) : (
                <div className="space-y-1.5 max-h-64 overflow-y-auto">
                  {sortedSessions.map(session => (
                    <div key={session.id}
                      className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all group ${session.id === currentSessionId ? 'bg-blue-50 border border-blue-200' : 'hover:bg-slate-50'}`}
                      onClick={() => { switchSession(session.id); setShowHistory(false) }}>
                      <MessageSquare size={15} className={session.id === currentSessionId ? 'text-blue-600' : 'text-slate-400'} />
                      <div className="flex-1 min-w-0">
                        <p className={`text-xs truncate ${session.id === currentSessionId ? 'text-blue-600 font-medium' : 'text-slate-600'}`}>{session.title}</p>
                        <p className="text-[10px] text-slate-400">{new Date(session.updatedAt).toLocaleDateString('zh-CN')} · {session.messages.length}条消息</p>
                      </div>
                      <button onClick={e => { e.stopPropagation(); deleteSession(session.id) }} className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 transition-all"><Trash2 size={13} /></button>
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
            <div className="flex justify-start gap-3 mb-6">
              <div className="w-9 h-9 rounded-full bg-blue-50 border border-blue-200 flex items-center justify-center flex-shrink-0 mt-1">
                <Sparkles size={16} className="text-blue-600" />
              </div>
              <div className="glass-card-static rounded-2xl rounded-tl-sm overflow-hidden max-w-[72%]">
                <div className="p-5 space-y-3">
                  <p className="text-sm font-semibold text-slate-700">你好，我是 LegalMind AI</p>
                  <p className="text-sm text-slate-600 leading-relaxed">
                    我是一个专业的中国法律智能助手，可以为您提供法律分析、条文解读和操作建议。
                    请直接输入您的法律问题，我会立即为您解答。
                  </p>
                  <div className="flex flex-wrap gap-2 pt-1">
                    <span className="px-2.5 py-1 rounded-full bg-blue-50 text-xs text-blue-600 border border-blue-100">民事纠纷</span>
                    <span className="px-2.5 py-1 rounded-full bg-purple-50 text-xs text-purple-600 border border-purple-100">合同审查</span>
                    <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-xs text-emerald-600 border border-emerald-100">劳动维权</span>
                    <span className="px-2.5 py-1 rounded-full bg-amber-50 text-xs text-amber-600 border border-amber-100">消费维权</span>
                  </div>
                </div>
              </div>
            </div>
            {/* 快捷问题 */}
            <div className="flex items-center gap-2 mb-4">
              <Lightbulb size={16} className="text-slate-400" />
              <span className="text-sm font-medium text-slate-500">不知道怎么问？试试这些问题</span>
              <RefreshCw size={14} className="text-slate-300 cursor-pointer hover:text-slate-500" />
            </div>
            <div className="grid grid-cols-4 gap-4">
              {QUICK_QUESTIONS.map((q, i) => (
                <motion.button key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                  onClick={() => { setInput(q.title); setTimeout(() => handleSend(), 100) }}
                  className="flex flex-col items-start p-5 rounded-xl border border-gray-200 bg-white hover:border-blue-300 hover:bg-blue-50/50 transition-all text-left group shadow-sm">
                  <span className="text-2xl mb-2">{q.icon}</span>
                  <span className={`text-sm ${q.color} font-medium leading-snug line-clamp-2 group-hover:text-blue-600`}>{q.title}</span>
                  <span className="text-xs text-slate-400 mt-1.5">{q.desc}</span>
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
                <div className="w-9 h-9 rounded-full bg-blue-50 border border-blue-200 flex items-center justify-center flex-shrink-0 mt-1">
                  <Sparkles size={16} className="text-blue-600" />
                </div>
              )}
              <div className={`max-w-[72%] ${msg.role === 'user' ? 'order-first' : ''}`}>
                {msg.role === 'user' ? (
                  <div className="chat-bubble-user px-4 py-3 rounded-2xl rounded-tr-sm">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                    <span className="text-xs text-blue-200 mt-1.5 block text-right">{msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                ) : (
                  <StructuredReply content={msg.content} isStreaming={isStreaming && msg.id === lastAssistantMsg?.id} />
                )}
              </div>
              {msg.role === 'user' && (
                <div className="w-9 h-9 rounded-full bg-blue-100 border border-blue-200 flex items-center justify-center flex-shrink-0 mt-1">
                  <User size={15} className="text-blue-600" />
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {/* 流式加载指示 */}
        {isStreaming && (!lastAssistantMsg || lastAssistantMsg.content) && (
          <div className="flex justify-start gap-3">
            <div className="w-9 h-9 rounded-full bg-blue-50 border border-blue-200 flex items-center justify-center flex-shrink-0">
              <Sparkles size={16} className="text-blue-600 animate-pulse" />
            </div>
            <div className="glass-card-static px-5 py-3 rounded-2xl rounded-tl-sm">
              <div className="flex items-center gap-2">
                {[0,120,240].map(d => <span key={d} className="w-2 h-2 bg-blue-600 rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }} />)}
                <span className="text-xs text-slate-400 ml-1">
                  {streamingPhase === 'retrieving' ? '正在检索法律知识…' : streamingPhase === 'generating' ? '正在生成回答…' : 'AI 正在分析...'}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* 错误提示 */}
        {error && (
          <div className="flex justify-center"><div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 max-w-md"><p className="text-xs text-red-600">{error}</p></div></div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 附件预览栏 */}
      {attachedFiles.length > 0 && (
        <div className="px-6 py-3 flex flex-wrap gap-2 border-t border-gray-200 bg-slate-50">
          {attachedFiles.map((f, i) => (
            <span key={i} className="flex items-center gap-1.5 text-xs bg-white text-slate-600 px-3 py-1.5 rounded-full border border-gray-200">
              📎 {f.name}<button onClick={() => setAttachedFiles(prev => prev.filter((_, idx) => idx !== i))} className="text-slate-400 hover:text-red-500"><X size={11} /></button>
            </span>
          ))}
        </div>
      )}

      {/* 引用文本栏 */}
      {quoteText && (
        <div className="px-6 py-3 border-t border-gray-200 bg-blue-50/50">
          <div className="flex items-start gap-2">
            <div className="w-0.5 h-8 bg-blue-500 rounded-full flex-shrink-0 mt-0.5" />
            <p className="text-xs text-slate-500 flex-1 line-clamp-2">{quoteText}</p>
            <button onClick={() => setQuoteText('')} className="text-slate-400 hover:text-slate-600 flex-shrink-0"><X size={14} /></button>
          </div>
        </div>
      )}

      {/* 输入区域 */}
      <div className="px-6 py-4 border-t border-gray-200 bg-white flex-shrink-0">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-end gap-3">
            <button onClick={() => fileInputRef.current?.click()}
              className="p-3 rounded-xl border border-gray-200 text-slate-400 hover:text-blue-600 hover:border-blue-300 transition-all flex-shrink-0">
              <Paperclip size={18} />
            </button>
            <input type="file" ref={fileInputRef} className="hidden" multiple accept=".pdf,.docx,.doc,.txt"
              onChange={(e) => { const fl = e.target.files; if (fl && fl.length) setAttachedFiles(prev => [...prev, ...Array.from(fl)]) } } />

            <div className="flex-1 relative">
              <textarea ref={textareaRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown}
                placeholder={quoteText ? '针对引用内容追问...' : '请输入您的法律问题，AI 为您提供专业诊断...'}
                rows={1} disabled={!authed || isStreaming}
                className={`w-full bg-white border rounded-xl px-4 py-3.5 pr-32 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30 resize-none min-h-[52px] max-h-32 transition-all disabled:opacity-40 ${
                  quoteText ? 'border-blue-300 focus:border-blue-500' : 'border-gray-300'
                }`} />
              <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
                <span className="text-xs text-slate-400 tabular-nums">{input.length}/2000</span>
                {isStreaming ? (
                  <button onClick={stopStreaming} className="p-2 rounded-lg bg-red-50 border border-red-200 text-red-500 hover:bg-red-100 transition-all">
                    <StopCircle size={16} />
                  </button>
                ) : (
                  <button onClick={handleSend} disabled={(!input.trim() && attachedFiles.length === 0) || !authed}
                    className="p-2 rounded-lg bg-blue-600 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-blue-700 transition-all">
                    <Send size={16} />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* 快捷标签 */}
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            {QUICK_TAGS.map((tag, i) => (
              <button key={i} onClick={() => setInput(tag.label)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-gray-200 text-xs text-slate-500 hover:text-blue-600 hover:border-blue-300 hover:bg-blue-50 transition-all">
                <tag.icon size={12} />{tag.label}
              </button>
            ))}
          </div>
          <div className="mt-3">
            <Disclaimer variant="compact" />
          </div>
        </div>
      </div>
    </main>
  )
}
