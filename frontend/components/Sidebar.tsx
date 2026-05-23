'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { MessageSquare, Scale, FileText, LayoutDashboard, Shield, BookOpen, Home, LogIn, LogOut, FolderOpen } from 'lucide-react'
import { useChatStore } from '@/store/useChatStore'
import { clearToken } from '@/app/lib/api'

const navItems = [
  { name: '工作空间', icon: LayoutDashboard, href: '/dashboard' },
  { name: '智能咨询', icon: MessageSquare, href: '/chat' },
  { name: '模拟法庭', icon: Scale, href: '/court' },
  { name: '合同审查', icon: FileText, href: '/documents' },
  { name: '法律知识库', icon: BookOpen, href: '/knowledge' },
  { name: '案件记忆', icon: FolderOpen, href: '/cases' },
]

interface SidebarProps {
  onLoginClick?: () => void
}

export default function Sidebar({ onLoginClick }: SidebarProps) {
  const pathname = usePathname()
  const { authed, setAuthed } = useChatStore()

  const handleLogout = () => {
    clearToken()
    setAuthed(false)
  }

  return (
    <aside className="w-[200px] h-screen bg-[#0a1628] flex flex-col border-r border-white/5">
      <Link href="/" className="p-5 flex items-center gap-3 border-b border-white/5 hover:bg-white/[0.02] transition-colors">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center flex-shrink-0">
          <Shield size={18} className="text-white" />
        </div>
        <div>
          <h1 className="text-base font-bold text-white leading-tight">智法: AI</h1>
          <p className="text-[10px] text-gray-400 leading-tight">智能法援助手</p>
        </div>
      </Link>

      <nav className="flex-1 p-3 space-y-1">
        {navItems.map(({ name, icon: Icon, href }) => {
          const isActive = href === '/' ? pathname === '/' : pathname === href || pathname?.startsWith(href + '/')
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-4 py-2.5 rounded-lg transition-all duration-200 text-sm ${
                isActive
                  ? 'bg-blue-500/15 text-blue-400 font-medium'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'
              }`}
            >
              <Icon size={18} className="flex-shrink-0" />
              <span>{name}</span>
            </Link>
          )
        })}
      </nav>

      <div className="p-4 border-t border-white/5">
        {authed ? (
          <button onClick={handleLogout} className="flex items-center gap-2 px-2 w-full text-gray-400 hover:text-red-400 transition-colors">
            <LogOut size={14} />
            <span className="text-xs">退出登录</span>
          </button>
        ) : (
          <button onClick={onLoginClick} className="flex items-center gap-2 px-2 w-full text-gray-400 hover:text-blue-400 transition-colors">
            <LogIn size={14} />
            <span className="text-xs">登录</span>
          </button>
        )}
      </div>
    </aside>
  )
}
