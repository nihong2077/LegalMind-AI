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
    <div className="min-h-screen bg-gradient-to-br from-white via-blue-50/30 to-indigo-50/20 flex items-center justify-center p-4 relative overflow-hidden">
      {/* Decorative background orbs */}
      <div className="absolute top-[-10%] left-[-5%] w-[500px] h-[500px] rounded-full bg-gradient-to-br from-blue-400/15 to-indigo-300/10 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-15%] right-[-8%] w-[600px] h-[600px] rounded-full bg-gradient-to-tl from-indigo-400/12 to-blue-300/8 blur-[140px] pointer-events-none" />
      <div className="absolute top-[40%] right-[15%] w-[300px] h-[300px] rounded-full bg-gradient-to-br from-blue-300/8 to-transparent blur-[100px] pointer-events-none animate-aura-pulse" />

      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
        className="w-full max-w-md relative z-10"
      >
        {/* Logo */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15 }}
          className="flex flex-col items-center mb-8"
        >
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center mb-4 shadow-lg shadow-blue-500/25">
            <Scale size={28} className="text-white" />
          </div>
          <h1 className="text-3xl font-display text-ink-900 tracking-wide">LegalMind AI</h1>
          <p className="text-sm text-ink-400 mt-1.5 font-body">智能司法协作平台</p>
        </motion.div>

        {/* Login / Register Card */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.25 }}
          className="glass-card-static p-8"
        >
          <h2 className="text-lg font-display text-ink-900 mb-1">{isRegister ? '注册' : '登录'}</h2>
          <p className="text-xs text-ink-400 mb-6 font-body">{isRegister ? '创建您的账号' : '使用您的账号登录系统'}</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs text-ink-500 mb-1.5 block font-body">用户名</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="请输入用户名"
                className="input-field"
                autoFocus
              />
            </div>

            <div>
              <label className="text-xs text-ink-500 mb-1.5 block font-body">密码</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="input-field pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-300 hover:text-blue-500 transition-colors duration-300"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {isRegister && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.3 }}
              >
                <label className="text-xs text-ink-500 mb-1.5 block font-body">确认密码</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  placeholder="请再次输入密码"
                  className="input-field"
                />
              </motion.div>
            )}

            {error && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2.5"
              >
                {error}
              </motion.div>
            )}

            <button
              type="submit"
              disabled={!username.trim() || !password.trim() || loading || (isRegister && !confirmPassword.trim())}
              className="primary-btn w-full flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed disabled:transform-none disabled:shadow-none"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : null}
              {loading ? (isRegister ? '注册中...' : '登录中...') : (isRegister ? '注册' : '登录')}
            </button>
          </form>

          <div className="mt-5 text-center">
            <button
              onClick={() => { setIsRegister(!isRegister); setError('') }}
              className="text-xs text-blue-500/70 hover:text-blue-600 transition-colors duration-300"
            >
              {isRegister ? '已有账号？去登录' : '没有账号？立即注册'}
            </button>
          </div>

          {!isRegister && (
            <p className="text-[10px] text-ink-300 text-center mt-4 font-body">
              默认账号：admin / admin
            </p>
          )}
        </motion.div>
      </motion.div>
    </div>
  )
}
