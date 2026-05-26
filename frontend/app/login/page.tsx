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
  const [isRegister, setIsRegister] = useState(false)
  const [confirmPassword, setConfirmPassword] = useState('')

  useEffect(() => {
    if (isAuthenticated()) {
      router.replace('/dashboard')
    }
  }, [router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) return
    setError('')

    if (isRegister) {
      if (password !== confirmPassword) {
        setError('两次输入的密码不一致')
        return
      }
      setLoading(true)
      try {
        // 注册接口调用（暂用登录接口模拟）
        await login(username, password)
        setAuthed(true)
        router.replace('/dashboard')
      } catch (err: unknown) {
        setError((err as Error).message || '注册失败')
      } finally {
        setLoading(false)
      }
      return
    }

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
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-slate-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-md"
      >
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-600 to-blue-700 flex items-center justify-center mb-4 shadow-lg shadow-blue-600/20">
            <Scale size={28} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-slate-800">LegalMind AI</h1>
          <p className="text-sm text-slate-500 mt-1">智能司法协作平台</p>
        </div>

        {/* 登录/注册卡片 */}
        <div className="border border-gray-200 rounded-2xl bg-white shadow-lg shadow-gray-200/50 p-8">
          <h2 className="text-lg font-semibold text-slate-800 mb-1">{isRegister ? '注册' : '登录'}</h2>
          <p className="text-xs text-slate-500 mb-6">{isRegister ? '创建您的账号' : '使用您的账号登录系统'}</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs text-slate-600 mb-1.5 block">用户名</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="请输入用户名"
                className="w-full bg-white border border-gray-300 rounded-xl px-4 py-2.5 text-sm text-slate-800
                         placeholder:text-slate-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30
                         transition-all"
                autoFocus
              />
            </div>

            <div>
              <label className="text-xs text-slate-600 mb-1.5 block">密码</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="w-full bg-white border border-gray-300 rounded-xl px-4 py-2.5 pr-10 text-sm text-slate-800
                           placeholder:text-slate-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30
                           transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {isRegister && (
              <div>
                <label className="text-xs text-slate-600 mb-1.5 block">确认密码</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  placeholder="请再次输入密码"
                  className="w-full bg-white border border-gray-300 rounded-xl px-4 py-2.5 text-sm text-slate-800
                           placeholder:text-slate-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30
                           transition-all"
                />
              </div>
            )}

            {error && (
              <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={!username.trim() || !password.trim() || loading || (isRegister && !confirmPassword.trim())}
              className="w-full py-2.5 rounded-xl bg-blue-600 text-white text-sm font-medium
                       hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed
                       flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : null}
              {loading ? (isRegister ? '注册中...' : '登录中...') : (isRegister ? '注册' : '登录')}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button
              onClick={() => { setIsRegister(!isRegister); setError('') }}
              className="text-xs text-blue-600 hover:text-blue-700 hover:underline transition-colors"
            >
              {isRegister ? '已有账号？去登录' : '没有账号？立即注册'}
            </button>
          </div>

          {!isRegister && (
            <p className="text-[10px] text-slate-400 text-center mt-4">
              默认账号：admin / admin
            </p>
          )}
        </div>
      </motion.div>
    </div>
  )
}
