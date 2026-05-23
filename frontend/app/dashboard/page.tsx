'use client'

import { useEffect, useState } from 'react'
import Sidebar from '@/components/Sidebar'
import LoginModal from '@/components/LoginModal'
import { MessageSquare, FileText, BookOpen, TrendingUp, Plus, FolderOpen, Gavel } from 'lucide-react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { getDashboardStats, getRecentCases, type DashboardStats, type CaseItem } from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
}

const item = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0 },
}

export default function DashboardPage() {
  const { authed } = useChatStore()
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [cases, setCases] = useState<CaseItem[]>([])
  const [loading, setLoading] = useState(true)

  // 从 localStorage 加载本地案件
  function loadLocalCases(): CaseItem[] {
    if (typeof window === 'undefined') return []
    try {
      const courtRaw = localStorage.getItem('legalmind_court_cases')
      const chatRaw = localStorage.getItem('legalmind_chat_history')
      const court: Array<{ id: string; title: string; createdAt: string }> = courtRaw ? JSON.parse(courtRaw) : []
      const chat: Array<{ id: string; title: string; createdAt: string }> = chatRaw ? JSON.parse(chatRaw) : []
      return [...court.map(c => ({ id: c.id, title: c.title, status: 'completed' as const, created_at: new Date(c.createdAt).toLocaleDateString('zh-CN') })),
              ...chat.map(c => ({ id: c.id, title: c.title, status: 'completed' as const, created_at: new Date(c.createdAt).toLocaleDateString('zh-CN') }))]
        .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)).slice(0, 5)
    } catch { return [] }
  }

  useEffect(() => {
    if (!authed) {
      setCases(loadLocalCases())
      setLoading(false)
      return
    }
    loadData()
  }, [authed])

  async function loadData() {
    setLoading(true)
    try {
      const [statsData, casesData] = await Promise.all([
        getDashboardStats(),
        getRecentCases(),
      ])
      setStats(statsData)
      setCases(casesData.length > 0 ? casesData : loadLocalCases())
    } catch {
      setCases(loadLocalCases())
    } finally {
      setLoading(false)
    }
  }

  const statCards = [
    { label: 'AI 对话次数', value: stats?.chat_count ?? 0, icon: MessageSquare, color: 'text-gold-400' },
    { label: '已分析文档', value: stats?.doc_count ?? 0, icon: FileText, color: 'text-blue-400' },
    { label: '法律知识条目', value: stats?.knowledge_count ?? 2450, icon: BookOpen, color: 'text-emerald-400' },
    { label: '案件处理效率', value: stats?.efficiency_gain ?? '+45%', icon: TrendingUp, color: 'text-purple-400' },
  ]

  const quickActions = [
    { title: 'AI 法律对话', desc: '向 AI 助手咨询法律问题', href: '/chat', icon: MessageSquare },
    { title: '文档智能分析', desc: '上传合同、诉状等法律文书', href: '/documents', icon: FileText },
    { title: '法律知识检索', desc: '搜索法律法规与判例', href: '/knowledge', icon: BookOpen },
  ]

  const statusLabel = (s: string) => {
    switch (s) {
      case 'completed': return { text: '已完成', cls: 'bg-green-400/10 text-green-400' }
      case 'analyzing': return { text: '分析中', cls: 'bg-gold-400/10 text-gold-400' }
      case 'pending': return { text: '待处理', cls: 'bg-gold-200/10 text-gold-200/50' }
      default: return { text: s, cls: 'bg-gold-200/10 text-gold-200/50' }
    }
  }

  return (
    <div className="flex h-screen">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />
      <main className="flex-1 overflow-y-auto p-8">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <h2 className="text-2xl font-bold text-gold-200 mb-1">工作台</h2>
          <p className="text-sm text-gold-200/40 mb-8">欢迎回来，以下是您的工作概览</p>
        </motion.div>

        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8"
        >
          {statCards.map((s) => (
            <motion.div key={s.label} variants={item} className="glass-card-static p-5">
              <div className="flex items-center justify-between mb-3">
                <s.icon size={18} className={s.color} />
                <span className="text-2xl font-bold text-gold-200">
                  {loading ? '...' : s.value}
                </span>
              </div>
              <p className="text-xs text-gold-200/40">{s.label}</p>
            </motion.div>
          ))}
        </motion.div>

        <div className="grid lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <h3 className="text-lg font-semibold text-gold-200">快速操作</h3>
            <motion.div
              variants={container}
              initial="hidden"
              animate="show"
              className="grid sm:grid-cols-3 gap-4"
            >
              {quickActions.map((a) => (
                <motion.div key={a.title} variants={item}>
                  <Link href={a.href} className="glass-card p-6 block group">
                    <div className="feature-glow" />
                    <a.icon size={24} className="text-gold-400 mb-4 relative z-10" />
                    <h4 className="font-semibold text-gold-200 mb-1 relative z-10">{a.title}</h4>
                    <p className="text-xs text-gold-200/40 relative z-10">{a.desc}</p>
                  </Link>
                </motion.div>
              ))}
            </motion.div>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gold-200">最近案件</h3>
              <div className="flex items-center gap-2">
                {authed && cases.length > 0 && (
                  <Link href="/cases" className="text-xs text-gold-400 hover:text-gold-300 flex items-center gap-1">
                    <FolderOpen size={12} /> 全部案件
                  </Link>
                )}
              </div>
            </div>
            {cases.length > 0 ? (
              <div className="space-y-3">
                {cases.map((c) => {
                  const sl = statusLabel(c.status)
                  return (
                    <div key={c.id} className="glass-card-static p-4">
                      <p className="text-sm text-gold-200 mb-2 truncate">{c.title}</p>
                      <div className="flex items-center justify-between">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full ${sl.cls}`}>
                          {sl.text}
                        </span>
                        <span className="text-[10px] text-gold-200/30">{c.created_at}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="glass-card-static p-6 text-center">
                <p className="text-xs text-gold-200/40 mb-3">
                  {authed ? '暂无案件记录' : '请先登录查看案件'}
                </p>
                {authed && (
                  <div className="flex flex-col items-center gap-2">
                    <Link href="/court" className="text-xs text-gold-400 hover:text-gold-300 flex items-center gap-1">
                      <Gavel size={12} /> 开始模拟法庭
                    </Link>
                    <Link href="/cases" className="text-xs text-gold-200/40 hover:text-gold-200/60 flex items-center gap-1">
                      <FolderOpen size={12} /> 查看案件记忆
                    </Link>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </main>
      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}
