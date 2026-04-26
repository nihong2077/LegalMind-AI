'use client'

import { useState, useEffect } from 'react'
import { Plus, FileText, Clock, CheckCircle, AlertCircle, LogIn } from 'lucide-react'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'

interface Case {
  id: number
  title: string
  description: string
  status: string
  case_type: string
  complexity_score: number
  created_at: string
  updated_at: string
}

export default function DashboardPage() {
  const [user, setUser] = useState<any>(null)
  const [cases, setCases] = useState<Case[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // 检查用户登录状态
    const userInfo = localStorage.getItem('user')
    if (userInfo) {
      setUser(JSON.parse(userInfo))
      fetchCases()
    } else {
      setLoading(false)
    }
  }, [])

  const fetchCases = async () => {
    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/cases', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || '获取案件列表失败')
      }

      const data = await response.json()
      setCases(data)
    } catch (err: any) {
      setError(err.message || '获取案件列表失败')
    } finally {
      setLoading(false)
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'draft':
        return <Clock size={16} className="text-blue-400" />
      case 'in_progress':
        return <AlertCircle size={16} className="text-yellow-400" />
      case 'completed':
        return <CheckCircle size={16} className="text-green-400" />
      default:
        return <FileText size={16} className="text-gold-400" />
    }
  }

  const getStatusText = (status: string) => {
    switch (status) {
      case 'draft':
        return '草稿'
      case 'in_progress':
        return '处理中'
      case 'completed':
        return '已完成'
      default:
        return status
    }
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-navy-950 relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(255,215,0,0.1),transparent_50%)"></div>
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,rgba(255,215,0,0.05),transparent_50%)"></div>
        
        <div className="relative z-10 w-full max-w-md p-8 bg-navy-900/80 backdrop-blur-lg rounded-2xl border border-gold-400/10 shadow-2xl text-center">
          <div className="mb-6">
            <div className="w-16 h-16 rounded-full bg-gold-400/20 flex items-center justify-center mx-auto mb-4">
              <LogIn size={32} className="text-gold-400" />
            </div>
            <h1 className="text-2xl font-bold text-gold-200 mb-2">请先登录</h1>
            <p className="text-gold-200/60">登录后查看您的案件和工作台</p>
          </div>
          <Link 
            href="/auth/login" 
            className="gold-btn inline-flex items-center gap-2"
          >
            <LogIn size={16} />
            立即登录
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-navy-950">
      <div className="max-w-7xl mx-auto px-6 py-16">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gold-200 mb-2">工作台</h1>
            <p className="text-gold-200/60">欢迎回来，{user.username}</p>
          </div>
          <Link 
            href="/chat" 
            className="gold-btn flex items-center gap-2"
          >
            <Plus size={16} />
            新建案件
          </Link>
        </div>

        {error && (
          <div className="p-4 bg-red-900/30 border border-red-500/30 rounded-lg text-sm text-red-400 mb-6">
            {error}
          </div>
        )}

        <div className="bg-navy-900/50 border border-gold-400/10 rounded-2xl p-6 shadow-xl">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-semibold text-gold-200">我的案件</h2>
            <span className="text-sm text-gold-200/60">共 {cases.length} 个案件</span>
          </div>

          {loading ? (
            <div className="flex justify-center py-12">
              <div className="flex gap-2">
                <span className="w-2 h-2 bg-gold-400/60 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-gold-400/60 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-gold-400/60 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          ) : cases.length === 0 ? (
            <div className="text-center py-16">
              <div className="w-16 h-16 rounded-full bg-gold-400/10 flex items-center justify-center mx-auto mb-4">
                <FileText size={32} className="text-gold-400/60" />
              </div>
              <h3 className="text-lg font-medium text-gold-200 mb-2">暂无案件</h3>
              <p className="text-gold-200/60 mb-6">您还没有创建任何案件</p>
              <Link 
                href="/chat" 
                className="gold-btn inline-flex items-center gap-2"
              >
                <Plus size={16} />
                开始第一个案件
              </Link>
            </div>
          ) : (
            <div className="space-y-4">
              <AnimatePresence>
                {cases.map((caseItem) => (
                  <motion.div
                    key={caseItem.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="glass-card-static p-6 rounded-xl border border-gold-400/10 hover:border-gold-400/30 transition-all"
                  >
                    <div className="flex items-start justify-between mb-4">
                      <h3 className="text-lg font-medium text-gold-200">{caseItem.title}</h3>
                      <div className="flex items-center gap-2 text-sm">
                        {getStatusIcon(caseItem.status)}
                        <span className="text-gold-200/70">{getStatusText(caseItem.status)}</span>
                      </div>
                    </div>
                    <p className="text-gold-200/60 text-sm mb-4 line-clamp-2">
                      {caseItem.description || '无描述'}
                    </p>
                    <div className="flex items-center justify-between text-xs text-gold-200/40">
                      <span>创建于 {new Date(caseItem.created_at).toLocaleDateString('zh-CN')}</span>
                      <span>复杂度: {caseItem.complexity_score}%</span>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
