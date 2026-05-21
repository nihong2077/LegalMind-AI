'use client'

import { useState } from 'react'
import { Shield, X, Loader2 } from 'lucide-react'
import { login, setToken } from '@/app/lib/api'

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

  if (!isOpen) return null

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="glass-card-static w-full max-w-sm mx-4 p-6 relative">
        <button onClick={onClose} className="absolute top-4 right-4 text-gold-200/40 hover:text-gold-200 transition-colors">
          <X size={18} />
        </button>

        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center mb-3">
            <Shield size={24} className="text-white" />
          </div>
          <h2 className="text-lg font-semibold text-gold-200">登录 LegalMind AI</h2>
          <p className="text-xs text-gold-200/40 mt-1">智能法援助手</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs text-gold-200/60 mb-1.5 block">用户名</label>
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
            <label className="text-xs text-gold-200/60 mb-1.5 block">密码</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="请输入密码"
              className="input-field"
            />
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
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

          <p className="text-[10px] text-gold-200/30 text-center">
            默认账号：admin / admin
          </p>
        </form>
      </div>
    </div>
  )
}
