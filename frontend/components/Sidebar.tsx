'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { MessageSquare, Scale, FileText, LayoutDashboard, Shield, BookOpen, LogIn, LogOut, FolderOpen } from 'lucide-react'
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
    <aside className="w-[240px] h-screen flex flex-col font-body bg-white border-r border-ink-100">
      {/* Logo */}
      <Link
        href="/"
        className="p-5 flex items-center gap-3 border-b border-ink-100 transition-colors duration-300 hover:bg-ink-50/80"
      >
        <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 bg-gradient-to-br from-blue-500 to-blue-600">
          <Scale size={18} className="text-white" />
        </div>
        <h1 className="text-base font-display font-semibold leading-tight text-ink-900">智法 AI</h1>
      </Link>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-0.5">
        {navItems.map(({ name, icon: Icon, href }) => {
          const isActive = href === '/' ? pathname === '/' : pathname === href || pathname?.startsWith(href + '/')
          return (
            <Link
              key={href}
              href={href}
              className={
                isActive
                  ? 'sidebar-link-active flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium text-blue-600 bg-blue-50/70 border-l-2 border-blue-500 transition-all duration-300'
                  : 'sidebar-link flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm text-ink-500 border-l-2 border-transparent hover:text-ink-900 hover:bg-ink-50/60 transition-all duration-300'
              }
            >
              <Icon size={17} className={`flex-shrink-0 ${isActive ? 'text-blue-500' : ''}`} />
              <span>{name}</span>
            </Link>
          )
        })}
      </nav>

      {/* Bottom: Login / Logout */}
      <div className="p-4 border-t border-ink-100">
        {authed ? (
          <button
            onClick={handleLogout}
            className="flex items-center gap-2.5 px-3 py-2 w-full rounded-lg text-ink-400 hover:text-red-500 hover:bg-red-50/70 transition-all duration-300"
          >
            <LogOut size={15} />
            <span className="text-xs">退出登录</span>
          </button>
        ) : (
          <button
            onClick={onLoginClick}
            className="flex items-center gap-2.5 px-3 py-2 w-full rounded-lg text-ink-400 hover:text-blue-600 hover:bg-blue-50/70 transition-all duration-300"
          >
            <LogIn size={15} />
            <span className="text-xs">登录</span>
          </button>
        )}
      </div>
    </aside>
  )
}
