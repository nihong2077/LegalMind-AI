'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Shield, X, Loader2 } from 'lucide-react'
import { login } from '@/app/lib/api'

interface LoginModalProps {
  isOpen: boolean
  onClose: () => void
  onLoginSuccess: () => void
}

export default function LoginModal({ isOpen, onClose, onLoginSuccess }: LoginModalProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      onLoginSuccess()
    } catch (err: any) {
      setError(err.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md">
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            className="glass-card-static w-full max-w-sm mx-4 p-6 relative"
          >
            <button onClick={onClose} className="absolute top-4 right-4 text-slate-400 hover:text-gold-300 transition-colors">
              <X size={18} />
            </button>

            <div className="flex flex-col items-center mb-6">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-gold-400 to-gold-500 flex items-center justify-center mb-3">
                <Shield size={24} className="text-navy-900" />
              </div>
              <h2 className="text-lg font-semibold text-slate-50 font-display">登录 LegalMind AI</h2>
              <p className="text-xs text-slate-400 mt-1 font-body">智能法援助手</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="text-xs text-slate-400 mb-1.5 block font-body">用户名</label>
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
                <label className="text-xs text-slate-400 mb-1.5 block font-body">密码</label>
                <input
                  type="password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="input-field"
                />
              </div>

              {error && (
                <div className="text-xs bg-red-900/30 border border-red-500/30 text-red-400 rounded-lg px-3 py-2 font-body">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={!username.trim() || !password.trim() || loading}
                className="gold-btn w-full flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : null}
                {loading ? '登录中...' : '登录'}
              </button>

              <p className="text-[10px] text-slate-500 text-center font-body">
                默认账号：admin / admin
              </p>
            </form>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
