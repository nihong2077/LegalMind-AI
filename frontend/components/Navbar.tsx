'use client'

import Link from 'next/link'
import { Scale, User, LogIn, LogOut } from 'lucide-react'
import { useState, useEffect } from 'react'

export default function Navbar() {
  const [user, setUser] = useState<any>(null)
  
  useEffect(() => {
    // 从localStorage获取用户信息
    const userInfo = localStorage.getItem('user')
    if (userInfo) {
      setUser(JSON.parse(userInfo))
    }
  }, [])
  
  const handleLogout = () => {
    localStorage.removeItem('user')
    localStorage.removeItem('token')
    setUser(null)
  }
  
  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-navy-900/80 backdrop-blur-xl border-b border-gold-400/10">
      <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-gold-400 to-gold-600 flex items-center justify-center">
            <Scale size={18} className="text-navy-900" />
          </div>
          <span className="text-lg font-bold text-gold-200">LegalMind AI</span>
        </Link>

        <nav className="hidden md:flex items-center gap-8">
          <Link href="/dashboard" className="text-sm text-gold-200/60 hover:text-gold-200 transition-colors">
            工作台
          </Link>
          <Link href="/chat" className="text-sm text-gold-200/60 hover:text-gold-200 transition-colors">
            AI 对话
          </Link>
          <Link href="/documents" className="text-sm text-gold-200/60 hover:text-gold-200 transition-colors">
            文档分析
          </Link>
        </nav>

        <div className="flex items-center gap-4">
          {user ? (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <User size={16} className="text-gold-400" />
                <span className="text-sm text-gold-200">{user.username}</span>
              </div>
              <button 
                onClick={handleLogout}
                className="text-sm text-gold-200/60 hover:text-gold-200 transition-colors flex items-center gap-1"
              >
                <LogOut size={14} />
                退出
              </button>
            </div>
          ) : (
            <Link href="/auth/login" className="gold-btn text-sm !px-4 !py-2 flex items-center gap-1">
              <LogIn size={14} />
              登录
            </Link>
          )}
        </div>
      </div>
    </header>
  )
}
