'use client'

import Link from 'next/link'
import { useState } from 'react'
import { Scale, Eye, EyeOff, Mail, User, Lock } from 'lucide-react'

export default function RegisterPage() {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: ''
  })
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData(prev => ({
      ...prev,
      [name]: value
    }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setLoading(true)

    try {
      console.log('开始注册请求:', formData)
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(formData)
      })

      console.log('注册请求响应:', response)
      
      if (!response.ok) {
        let errorMessage = '注册失败'
        try {
          const errorData = await response.json()
          console.log('注册失败:', errorData)
          if (errorData.detail) {
            errorMessage = errorData.detail
          } else if (errorData.error) {
            errorMessage = errorData.error
          } else {
            errorMessage = `请求失败: ${response.status} ${response.statusText}`
          }
        } catch (e) {
          console.error('解析错误响应失败:', e)
          errorMessage = `请求失败: ${response.status} ${response.statusText}`
        }
        throw new Error(errorMessage)
      }

      const data = await response.json()
      console.log('注册成功:', data)
      setSuccess('注册成功，请登录')
      // 3秒后跳转到登录页面
      setTimeout(() => {
        window.location.href = '/auth/login'
      }, 3000)
    } catch (err: any) {
      console.error('注册错误:', err)
      // 更好地处理网络错误
      let errorMessage = '注册失败'
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        errorMessage = '无法连接到服务器，请检查网络连接'
      } else if (err.message) {
        errorMessage = err.message
      } else if (typeof err === 'string') {
        errorMessage = err
      }
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-navy-950 relative overflow-hidden">
      {/* 背景装饰 */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(255,215,0,0.1),transparent_50%)"></div>
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,rgba(255,215,0,0.05),transparent_50%)"></div>
      
      <div className="relative z-10 w-full max-w-md p-8 bg-navy-900/80 backdrop-blur-lg rounded-2xl border border-gold-400/10 shadow-2xl">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center mb-4">
            <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-gold-400 to-gold-600 flex items-center justify-center">
              <Scale size={24} className="text-navy-900" />
            </div>
          </div>
          <h1 className="text-2xl font-bold text-gold-200">LegalMind AI</h1>
          <p className="text-sm text-gold-200/60 mt-2">专业的法律智能助手</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && (
            <div className="p-3 bg-red-900/30 border border-red-500/30 rounded-lg text-sm text-red-400">
              {error}
            </div>
          )}

          {success && (
            <div className="p-3 bg-green-900/30 border border-green-500/30 rounded-lg text-sm text-green-400">
              {success}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gold-200/80 mb-2">
              用户名
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <User size={18} className="text-gold-400/60" />
              </div>
              <input
                type="text"
                name="username"
                value={formData.username}
                onChange={handleInputChange}
                required
                className="w-full pl-10 pr-4 py-3 bg-navy-800/50 border border-gold-400/20 rounded-lg text-gold-200 placeholder-gold-200/30 focus:outline-none focus:ring-2 focus:ring-gold-400/50 focus:border-gold-400/50 transition-colors"
                placeholder="请输入用户名"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gold-200/80 mb-2">
              邮箱
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Mail size={18} className="text-gold-400/60" />
              </div>
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleInputChange}
                required
                className="w-full pl-10 pr-4 py-3 bg-navy-800/50 border border-gold-400/20 rounded-lg text-gold-200 placeholder-gold-200/30 focus:outline-none focus:ring-2 focus:ring-gold-400/50 focus:border-gold-400/50 transition-colors"
                placeholder="请输入邮箱"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gold-200/80 mb-2">
              密码
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Lock size={18} className="text-gold-400/60" />
              </div>
              <input
                type={showPassword ? 'text' : 'password'}
                name="password"
                value={formData.password}
                onChange={handleInputChange}
                required
                minLength={6}
                className="w-full pl-10 pr-10 py-3 bg-navy-800/50 border border-gold-400/20 rounded-lg text-gold-200 placeholder-gold-200/30 focus:outline-none focus:ring-2 focus:ring-gold-400/50 focus:border-gold-400/50 transition-colors"
                placeholder="请输入密码（至少6位）"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center"
              >
                {showPassword ? (
                  <EyeOff size={18} className="text-gold-400/60 hover:text-gold-400 transition-colors" />
                ) : (
                  <Eye size={18} className="text-gold-400/60 hover:text-gold-400 transition-colors" />
                )}
              </button>
            </div>
          </div>

          <div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-4 bg-gradient-to-r from-gold-500 to-gold-600 text-navy-900 font-medium rounded-lg hover:from-gold-400 hover:to-gold-500 focus:outline-none focus:ring-2 focus:ring-gold-400/50 transition-all disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading ? '注册中...' : '注册'}
            </button>
          </div>
        </form>

        <div className="mt-8 text-center">
          <p className="text-sm text-gold-200/60">
            已有账号？{' '}
            <Link 
              href="/auth/login" 
              className="text-gold-400 hover:text-gold-300 transition-colors"
            >
              立即登录
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
