'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Paperclip, Sparkles, RotateCcw, Copy, Check } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  agent?: string
}

const suggestedQuestions = [
  '劳动合同解除有哪些法定情形？',
  '如何起诉离婚？需要准备什么材料？',
  '房屋租赁合同中的违约金如何约定？',
  '交通事故赔偿标准是什么？',
]

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [attachedFiles, setAttachedFiles] = useState<string[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  const handleSend = async () => {
    if (!input.trim()) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsTyping(true)

    setTimeout(() => {
      const aiMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `根据您的问题「${input}」，我为您整理了以下法律分析：\n\n根据《中华人民共和国民法典》相关规定，该问题涉及多个法律要点。建议您进一步咨询专业律师以获取针对您具体情况的详细法律意见。\n\n⚠️ 以上内容仅供参考，不构成法律建议。`,
        timestamp: new Date(),
        agent: '法律分析助手',
      }
      setMessages((prev) => [...prev, aiMsg])
      setIsTyping(false)
    }, 2000)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const copyMessage = (id: string, content: string) => {
    navigator.clipboard.writeText(content)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    const names = Array.from(files).map((f) => f.name)
    setAttachedFiles((prev) => [...prev, ...names])
  }

  const clearChat = () => {
    setMessages([])
    setAttachedFiles([])
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-gold-400/20 to-gold-600/10
                            flex items-center justify-center mb-6 border border-gold-400/20">
              <Sparkles size={36} className="text-gold-400" />
            </div>
            <h2 className="text-2xl font-bold text-gold-200 mb-2">LegalMind AI 助手</h2>
            <p className="text-gold-200/50 mb-8 max-w-md">
              面向民事法律场景的智能司法协作系统，为您提供专业的法律分析与建议
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
              {suggestedQuestions.map((q) => (
                <button
                  key={q}
                  onClick={() => { setInput(q) }}
                  className="glass-card-static p-4 text-left text-sm text-gold-200/70
                             hover:text-gold-200 hover:border-gold-400/30 transition-all duration-300 cursor-pointer"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        <AnimatePresence>
          {messages.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div className={msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant'}>
                {msg.agent && (
                  <div className="flex items-center gap-2 mb-2">
                    <Sparkles size={12} className="text-gold-400" />
                    <span className="text-xs text-gold-400 font-medium">{msg.agent}</span>
                  </div>
                )}
                <div className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</div>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-[10px] text-gold-200/30">
                    {msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                  </span>
                  {msg.role === 'assistant' && (
                    <button
                      onClick={() => copyMessage(msg.id, msg.content)}
                      className="text-gold-200/30 hover:text-gold-400 transition-colors"
                    >
                      {copiedId === msg.id ? <Check size={12} /> : <Copy size={12} />}
                    </button>
                  )}
                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {isTyping && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex justify-start"
          >
            <div className="chat-bubble-assistant">
              <div className="flex items-center gap-2">
                <div className="flex gap-1">
                  <span className="w-2 h-2 bg-gold-400/60 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-2 h-2 bg-gold-400/60 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-2 h-2 bg-gold-400/60 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
                <span className="text-xs text-gold-200/40">AI 正在分析...</span>
              </div>
            </div>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {attachedFiles.length > 0 && (
        <div className="px-4 py-2 flex flex-wrap gap-2 border-t border-gold-400/10">
          {attachedFiles.map((f, i) => (
            <span key={i} className="text-xs bg-gold-400/10 text-gold-400 px-3 py-1 rounded-full border border-gold-400/20">
              📎 {f}
            </span>
          ))}
        </div>
      )}

      <div className="p-4 border-t border-gold-400/10">
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="mb-3 flex items-center gap-1.5 text-xs text-gold-200/40 hover:text-gold-400 transition-colors"
          >
            <RotateCcw size={12} /> 清空对话
          </button>
        )}
        <div className="flex items-end gap-3">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="p-2.5 rounded-xl border border-gold-400/15 text-gold-200/40
                       hover:text-gold-400 hover:border-gold-400/30 transition-all"
          >
            <Paperclip size={18} />
          </button>
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            multiple
            onChange={handleFileUpload}
          />
          <div className="flex-1 relative">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入法律问题，按 Enter 发送..."
              rows={1}
              className="input-field resize-none pr-12 min-h-[44px] max-h-32"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="absolute right-2 bottom-2 p-2 rounded-lg bg-gold-400 text-navy-900
                         disabled:opacity-30 disabled:cursor-not-allowed
                         hover:bg-gold-300 transition-all"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
