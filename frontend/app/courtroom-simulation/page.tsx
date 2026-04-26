'use client'

import { useState, useRef, useEffect } from 'react'
import { Gavel, User, Users, Play, RotateCcw, FileText } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import Navbar from '@/components/Navbar'
import Footer from '@/components/Footer'
import Link from 'next/link'

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
      case 'plaintiff': return 'text-blue-400 bg-blue-400/20'
      case 'defendant': return 'text-red-400 bg-red-400/20'
      case 'judge': return 'text-gold-400 bg-gold-400/20'
      default: return 'text-gold-200 bg-navy-800/50'
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-navy-950">
      <Navbar />
      
      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-12">
        <div className="mb-8">
          <Link href="/" className="text-gold-400 hover:text-gold-300 flex items-center gap-2 mb-6">
            ← 返回首页
          </Link>
          <h1 className="text-3xl font-bold text-gold-100 mb-2">法庭模拟</h1>
          <p className="text-gold-200/60">
            模拟法庭辩论过程，原告和被告律师轮流辩论，最后由法官总结
          </p>
        </div>

        <div className="grid lg:grid-cols-3 gap-8">
          {/* 输入区域 */}
          <div className="lg:col-span-1 space-y-6">
            <div className="glass-card p-6 rounded-xl border border-gold-400/10">
              <h2 className="text-xl font-bold text-gold-100 mb-4">案件描述</h2>
              <textarea
                value={caseDescription}
                onChange={(e) => setCaseDescription(e.target.value)}
                placeholder="请详细描述您的案件情况..."
                className="w-full h-64 bg-navy-800/50 border border-gold-400/20 rounded-lg p-4 text-gold-200 placeholder-gold-200/40 focus:outline-none focus:border-gold-400/50 resize-none"
                disabled={isSimulating}
              />
              <div className="flex gap-4 mt-4">
                <button
                  onClick={handleStartSimulation}
                  disabled={isSimulating || !caseDescription.trim()}
                  className="gold-btn flex-1 flex items-center justify-center gap-2"
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
                  className="px-4 py-2 bg-navy-800/50 border border-gold-400/20 text-gold-200 rounded-lg hover:bg-navy-800/70 transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                  <RotateCcw className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* 角色介绍 */}
            <div className="glass-card p-6 rounded-xl border border-gold-400/10">
              <h2 className="text-xl font-bold text-gold-100 mb-4">参与角色</h2>
              <div className="space-y-4">
                <div className="flex items-center gap-4 p-3 bg-blue-400/10 border border-blue-400/20 rounded-lg">
                  <div className="w-10 h-10 rounded-full bg-blue-400/20 flex items-center justify-center">
                    <User className="w-5 h-5 text-blue-400" />
                  </div>
                  <div>
                    <p className="font-medium text-blue-400">原告律师</p>
                    <p className="text-sm text-gold-200/60">代表原告进行陈述和辩护</p>
                  </div>
                </div>
                <div className="flex items-center gap-4 p-3 bg-red-400/10 border border-red-400/20 rounded-lg">
                  <div className="w-10 h-10 rounded-full bg-red-400/20 flex items-center justify-center">
                    <User className="w-5 h-5 text-red-400" />
                  </div>
                  <div>
                    <p className="font-medium text-red-400">被告律师</p>
                    <p className="text-sm text-gold-200/60">代表被告进行陈述和辩护</p>
                  </div>
                </div>
                <div className="flex items-center gap-4 p-3 bg-gold-400/10 border border-gold-400/20 rounded-lg">
                  <div className="w-10 h-10 rounded-full bg-gold-400/20 flex items-center justify-center">
                    <Gavel className="w-5 h-5 text-gold-400" />
                  </div>
                  <div>
                    <p className="font-medium text-gold-400">法官</p>
                    <p className="text-sm text-gold-200/60">主持庭审，作出裁判</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 法庭模拟区域 */}
          <div className="lg:col-span-2">
            <div className="glass-card rounded-xl border border-gold-400/10 h-[calc(100vh-300px)] flex flex-col">
              {/* 法官席位 */}
              <div className="p-6 border-b border-gold-400/10 bg-navy-900/30">
                <div className="flex items-center justify-center gap-4">
                  <div className="w-16 h-16 rounded-full bg-gold-400/20 flex items-center justify-center">
                    <Gavel className="w-8 h-8 text-gold-400" />
                  </div>
                  <div className="text-center">
                    <p className="font-bold text-gold-100 text-lg">法官</p>
                    <p className="text-sm text-gold-200/60">
                      {currentSpeaker === 'judge' ? '正在发言...' : '等待发言'}
                    </p>
                  </div>
                </div>
              </div>

              {/* 辩论区域 */}
              <div className="flex-1 overflow-y-auto p-6">
                <div className="grid grid-cols-2 gap-8 mb-8">
                  <div className={`p-6 rounded-xl border ${currentSpeaker === 'plaintiff' ? 'border-blue-400/50 bg-blue-400/10' : 'border-blue-400/20 bg-navy-800/30'} transition-all`}>
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-12 h-12 rounded-full bg-blue-400/20 flex items-center justify-center">
                        <Users className="w-6 h-6 text-blue-400" />
                      </div>
                      <div>
                        <p className="font-bold text-blue-400">原告律师</p>
                        <p className="text-sm text-gold-200/60">
                          {currentSpeaker === 'plaintiff' ? '正在发言...' : '等待发言'}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className={`p-6 rounded-xl border ${currentSpeaker === 'defendant' ? 'border-red-400/50 bg-red-400/10' : 'border-red-400/20 bg-navy-800/30'} transition-all`}>
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-12 h-12 rounded-full bg-red-400/20 flex items-center justify-center">
                        <Users className="w-6 h-6 text-red-400" />
                      </div>
                      <div>
                        <p className="font-bold text-red-400">被告律师</p>
                        <p className="text-sm text-gold-200/60">
                          {currentSpeaker === 'defendant' ? '正在发言...' : '等待发言'}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 消息记录 */}
                {messages.length > 0 && (
                  <div className="space-y-4">
                    <h3 className="text-lg font-bold text-gold-100 flex items-center gap-2">
                      <FileText className="w-5 h-5" /> 庭审记录
                    </h3>
                    <AnimatePresence>
                      {messages.map((message) => (
                        <motion.div
                          key={message.id}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          className={`p-4 rounded-lg border ${
                            message.role === 'plaintiff'
                              ? 'bg-blue-400/10 border-blue-400/20'
                              : message.role === 'defendant'
                              ? 'bg-red-400/10 border-red-400/20'
                              : 'bg-gold-400/10 border-gold-400/20'
                          }`}
                        >
                          <div className="flex items-center gap-3 mb-2">
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                              message.role === 'plaintiff'
                                ? 'bg-blue-400/20 text-blue-400'
                                : message.role === 'defendant'
                                ? 'bg-red-400/20 text-red-400'
                                : 'bg-gold-400/20 text-gold-400'
                            }`}>
                              {message.role === 'judge' ? (
                                <Gavel className="w-4 h-4" />
                              ) : (
                                <User className="w-4 h-4" />
                              )}
                            </div>
                            <div className="flex-1">
                              <span className={`font-bold ${
                                message.role === 'plaintiff'
                                  ? 'text-blue-400'
                                  : message.role === 'defendant'
                                  ? 'text-red-400'
                                  : 'text-gold-400'
                              }`}>
                                {getRoleName(message.role)}
                              </span>
                              <span className="text-xs text-gold-200/40 ml-2">
                                {message.timestamp.toLocaleTimeString()}
                              </span>
                            </div>
                          </div>
                          <p className="text-gold-200/80 whitespace-pre-wrap pl-11">
                            {message.content}
                          </p>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                )}

                {messages.length === 0 && !isSimulating && (
                  <div className="flex flex-col items-center justify-center h-48 text-center">
                    <Gavel className="w-16 h-16 text-gold-400/30 mb-4" />
                    <p className="text-gold-200/60">点击开始模拟，观看法庭辩论</p>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            </div>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  )
}
