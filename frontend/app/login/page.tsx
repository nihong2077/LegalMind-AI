'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { Shield, Loader2, Scale, Eye, EyeOff } from 'lucide-react'
import { login, isAuthenticated } from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

export default function LoginPage() {
  const router = useRouter()
  const { setAuthed } = useChatStore()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isAuthenticated()) {
      router.replace('/dashboard')
    }
  }, [router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) return
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      setAuthed(true)
      router.replace('/dashboard')
    } catch (err: unknown) {
      setError((err as Error).message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a1628] flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-md"
      >
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center mb-4 shadow-lg shadow-blue-500/20">
            <Scale size={28} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gold-200">LegalMind AI</h1>
          <p className="text-sm text-gold-200/40 mt-1">智能司法协作平台</p>
        </div>

        {/* 登录卡片 */}
        <div className="border border-white/10 rounded-2xl bg-white/[0.02] backdrop-blur-xl p-8">
          <h2 className="text-lg font-semibold text-gold-200 mb-1">登录</h2>
          <p className="text-xs text-gold-200/40 mb-6">使用您的账号登录系统</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs text-gold-200/60 mb-1.5 block">用户名</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="请输入用户名"
                className="w-full bg-white/[0.04] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-gold-200
                         placeholder:text-gold-200/25 focus:outline-none focus:border-blue-400/40 focus:ring-1 focus:ring-blue-400/10
                         transition-all"
                autoFocus
              />
            </div>

            <div>
              <label className="text-xs text-gold-200/60 mb-1.5 block">密码</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="w-full bg-white/[0.04] border border-white/10 rounded-xl px-4 py-2.5 pr-10 text-sm text-gold-200
                           placeholder:text-gold-200/25 focus:outline-none focus:border-blue-400/40 focus:ring-1 focus:ring-blue-400/10
                           transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gold-200/30 hover:text-gold-200/60 transition-colors"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {error && (
              <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={!username.trim() || !password.trim() || loading}
              className="w-full py-2.5 rounded-xl bg-blue-600 text-white text-sm font-medium
                       hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed
                       flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : null}
              {loading ? '登录中...' : '登录'}
            </button>
          </form>

          <p className="text-[10px] text-gold-200/30 text-center mt-6">
            默认账号：admin / admin
          </p>
        </div>
      </motion.div>
    </div>
  )
}