'use client'

import { useState, useRef, useEffect } from 'react'
import { Gavel, User, Play, RotateCcw, MessageSquare } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import Sidebar from '@/components/Sidebar'

interface CourtMessage {
  id: string
  role: 'plaintiff' | 'defendant' | 'judge'
  content: string
  timestamp: Date
}

export default function CourtroomSimulationPage() {
  const [caseDescription, setCaseDescription] = useState('')
  const [isSimulating, setIsSimulating] = useState(false)
  const [messages, setMessages] = useState<CourtMessage[]>([])
  const [currentSpeaker, setCurrentSpeaker] = useState<'plaintiff' | 'defendant' | 'judge' | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleStartSimulation = async () => {
    if (!caseDescription.trim() || isSimulating) return

    setIsSimulating(true)
    setMessages([])

    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/courtroom-simulation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : '',
        },
        body: JSON.stringify({ case_description: caseDescription }),
      })

      if (!response.ok) {
        throw new Error('模拟失败')
      }

      // 流式响应
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      
      if (reader) {
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.role && data.content) {
                  const newMessage: CourtMessage = {
                    id: Date.now().toString() + Math.random(),
                    role: data.role as 'plaintiff' | 'defendant' | 'judge',
                    content: data.content,
                    timestamp: new Date(),
                  }
                  setCurrentSpeaker(newMessage.role)
                  setMessages(prev => [...prev, newMessage])
                  
                  // 短暂延迟后清除当前发言者，增加动画效果
                  setTimeout(() => setCurrentSpeaker(null), 1500)
                }
              } catch (e) {
                console.error('解析失败', e)
              }
            }
          }
        }
      }
    } catch (error) {
      console.error('模拟错误:', error)
      const errorMessage: CourtMessage = {
        id: Date.now().toString(),
        role: 'judge',
        content: '模拟过程中出现错误，请稍后重试。',
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setIsSimulating(false)
      setCurrentSpeaker(null)
    }
  }

  const handleReset = () => {
    setCaseDescription('')
    setMessages([])
    setCurrentSpeaker(null)
    setIsSimulating(false)
  }

  const getRoleName = (role: string) => {
    switch (role) {
      case 'plaintiff': return '原告律师'
      case 'defendant': return '被告律师'
      case 'judge': return '法官'
      default: return '未知'
    }
  }

  const getRoleColor = (role: string) => {
    switch (role) {
      case 'plaintiff': return 'text-blue-400'
      case 'defendant': return 'text-red-400'
      case 'judge': return 'text-gold-400'
      default: return 'text-gold-200'
    }
  }

  const getRoleBgColor = (role: string) => {
    switch (role) {
      case 'plaintiff': return 'bg-blue-400/10 border-blue-400/20'
      case 'defendant': return 'bg-red-400/10 border-red-400/20'
      case 'judge': return 'bg-gold-400/10 border-gold-400/20'
      default: return 'bg-navy-800/50 border-gold-400/10'
    }
  }

  const getRoleAvatar = (role: string) => {
    switch (role) {
      case 'plaintiff': return '👨‍💼'
      case 'defendant': return '👩‍💼'
      case 'judge': return '👨‍⚖️'
      default: return '👤'
    }
  }

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-0">
        <div className="px-6 py-4 border-b border-gold-400/10 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gold-200">法庭模拟</h2>
            <p className="text-xs text-gold-200/40">原告和被告律师轮流辩论，法官决定是否继续，最后由法官总结</p>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid lg:grid-cols-3 gap-8 max-w-6xl mx-auto">
            {/* 输入区域 */}
            <div className="space-y-6">
              <motion.div 
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.6 }}
                className="glass-card p-6 rounded-xl border border-gold-400/10"
              >
                <h2 className="text-xl font-bold text-gold-100 mb-4">案件描述</h2>
                <textarea
                  value={caseDescription}
                  onChange={(e) => setCaseDescription(e.target.value)}
                  placeholder="请详细描述您的案件情况..."
                  className="input-field h-64 resize-none"
                  disabled={isSimulating}
                />
                <div className="flex gap-4 mt-6">
                  <button
                    onClick={handleStartSimulation}
                    disabled={isSimulating || !caseDescription.trim()}
                    className="gold-btn flex-1 flex items-center justify-center gap-2 py-3"
                  >
                    {isSimulating ? (
                      <>
                        <span className="animate-pulse">模拟中...</span>
                      </>
                    ) : (
                      <>
                        <Play className="w-5 h-5" /> 开始模拟
                      </>
                    )}
                  </button>
                  <button
                    onClick={handleReset}
                    disabled={isSimulating}
                    className="px-4 py-3 bg-navy-800/60 border border-gold-400/20 text-gold-200 rounded-lg hover:bg-navy-800/80 transition-colors disabled:opacity-50 flex items-center gap-2"
                  >
                    <RotateCcw className="w-5 h-5" />
                  </button>
                </div>
              </motion.div>

              {/* 角色介绍 */}
              <motion.div 
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.6, delay: 0.2 }}
                className="glass-card p-6 rounded-xl border border-gold-400/10"
              >
                <h2 className="text-xl font-bold text-gold-100 mb-6">参与角色</h2>
                <div className="space-y-4">
                  <motion.div 
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4 }}
                    className="flex items-center gap-4 p-4 bg-blue-400/10 border border-blue-400/20 rounded-lg"
                  >
                    <div className="w-14 h-14 rounded-full bg-blue-400/20 flex items-center justify-center text-2xl">
                      👨‍💼
                    </div>
                    <div>
                      <p className="font-medium text-blue-400">原告律师</p>
                      <p className="text-sm text-gold-200/60">代表原告进行陈述和辩护</p>
                    </div>
                  </motion.div>
                  <motion.div 
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, delay: 0.1 }}
                    className="flex items-center gap-4 p-4 bg-red-400/10 border border-red-400/20 rounded-lg"
                  >
                    <div className="w-14 h-14 rounded-full bg-red-400/20 flex items-center justify-center text-2xl">
                      👩‍💼
                    </div>
                    <div>
                      <p className="font-medium text-red-400">被告律师</p>
                      <p className="text-sm text-gold-200/60">代表被告进行陈述和辩护</p>
                    </div>
                  </motion.div>
                  <motion.div 
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, delay: 0.2 }}
                    className="flex items-center gap-4 p-4 bg-gold-400/10 border border-gold-400/20 rounded-lg"
                  >
                    <div className="w-14 h-14 rounded-full bg-gold-400/20 flex items-center justify-center text-2xl">
                      👨‍⚖️
                    </div>
                    <div>
                      <p className="font-medium text-gold-400">法官</p>
                      <p className="text-sm text-gold-200/60">主持庭审，作出裁判</p>
                    </div>
                  </motion.div>
                </div>
              </motion.div>
            </div>

            {/* 法庭模拟区域 */}
            <motion.div 
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.6, delay: 0.4 }}
              className="lg:col-span-2 space-y-6"
            >
              {/* 聊天对话框 */}
              <div className="glass-card rounded-xl border border-gold-400/10 h-[700px] flex flex-col">
                <div className="p-4 border-b border-gold-400/10 flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-gold-400" />
                  <h3 className="text-lg font-bold text-gold-100">法庭辩论</h3>
                </div>
                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                  <AnimatePresence>
                    {messages.map((message) => (
                      <motion.div
                        key={message.id}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.4 }}
                        className={`flex items-start gap-4 ${
                          message.role === 'plaintiff' ? 'justify-start' : 
                          message.role === 'defendant' ? 'justify-start' : 'justify-center'
                        }`}
                      >
                        <div className={`w-14 h-14 rounded-full flex items-center justify-center text-2xl ${getRoleBgColor(message.role)} shadow-lg shadow-gold-400/10`}>
                          {getRoleAvatar(message.role)}
                        </div>
                        <div className={`max-w-[70%] ${message.role === 'judge' ? 'text-center' : ''}`}>
                          <div className={`font-medium ${getRoleColor(message.role)} mb-2`}>
                            {getRoleName(message.role)}
                          </div>
                          <div className={`p-5 rounded-lg ${getRoleBgColor(message.role)} shadow-md`}>
                            <p className="text-gold-200/90 whitespace-pre-wrap leading-relaxed">
                              {message.content}
                            </p>
                          </div>
                          <div className="text-xs text-gold-200/40 mt-2">
                            {message.timestamp.toLocaleTimeString()}
                          </div>
                        </div>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  
                  {messages.length === 0 && !isSimulating && (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                      <motion.div
                        animate={{ scale: [1, 1.05, 1] }}
                        transition={{ duration: 2, repeat: Infinity, repeatType: "reverse" }}
                      >
                        <MessageSquare className="w-24 h-24 text-gold-400/30 mb-8" />
                      </motion.div>
                      <h3 className="text-xl font-bold text-gold-100 mb-3">准备开始</h3>
                      <p className="text-gold-200/60 max-w-md">
                        输入案件描述并点击"开始模拟"按钮，观看原告和被告律师的辩论过程
                      </p>
                    </div>
                  )}
                  
                  {isSimulating && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="flex items-center justify-center gap-3 mt-8"
                    >
                      <motion.div
                        animate={{ y: [0, -10, 0] }}
                        transition={{ duration: 1, repeat: Infinity, repeatType: "loop" }}
                        className="w-3 h-3 bg-gold-400 rounded-full"
                      />
                      <motion.div
                        animate={{ y: [0, -10, 0] }}
                        transition={{ duration: 1, repeat: Infinity, repeatType: "loop", delay: 0.2 }}
                        className="w-3 h-3 bg-gold-400 rounded-full"
                      />
                      <motion.div
                        animate={{ y: [0, -10, 0] }}
                        transition={{ duration: 1, repeat: Infinity, repeatType: "loop", delay: 0.4 }}
                        className="w-3 h-3 bg-gold-400 rounded-full"
                      />
                    </motion.div>
                  )}
                  
                  <div ref={messagesEndRef} />
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </main>
    </div>
  )
}
