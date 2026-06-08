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
    <aside
      className="w-[220px] h-screen flex flex-col font-body border-r"
      style={{
        background: 'linear-gradient(180deg, #0a1628 0%, #0f1f3d 50%, #0a1628 100%)',
        borderRightColor: 'rgba(59, 125, 216, 0.08)',
      }}
    >
      {/* Logo */}
      <Link
        href="/"
        className="p-5 flex items-center gap-3 border-b transition-colors duration-300 hover:bg-white/[0.03]"
        style={{ borderBottomColor: 'rgba(59, 125, 216, 0.08)' }}
      >
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{
            background: 'linear-gradient(135deg, #c9a84c 0%, #f0d78c 50%, #c9a84c 100%)',
          }}
        >
          <Scale size={18} className="text-navy-900" />
        </div>
        <div>
          <h1 className="text-base font-bold leading-tight text-gold-300">智法 AI</h1>
          <p className="text-[10px] leading-tight text-white/30">智能法援助手</p>
        </div>
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
                  ? 'sidebar-link-active flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium text-gold-300 border-l-2 border-gold-300 bg-gold-300/[0.06] transition-all duration-300'
                  : 'sidebar-link flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm text-white/50 border-l-2 border-transparent hover:text-white/90 hover:bg-white/[0.04] transition-all duration-300'
              }
            >
              <Icon size={17} className={`flex-shrink-0 ${isActive ? 'text-gold-300' : ''}`} />
              <span>{name}</span>
            </Link>
          )
        })}
      </nav>

      {/* Bottom: Login / Logout */}
      <div className="p-4 border-t" style={{ borderTopColor: 'rgba(59, 125, 216, 0.08)' }}>
        {authed ? (
          <button
            onClick={handleLogout}
            className="flex items-center gap-2.5 px-3 py-2 w-full rounded-lg text-white/40 hover:text-red-400 hover:bg-red-400/[0.06] transition-all duration-300"
          >
            <LogOut size={15} />
            <span className="text-xs">退出登录</span>
          </button>
        ) : (
          <button
            onClick={onLoginClick}
            className="flex items-center gap-2.5 px-3 py-2 w-full rounded-lg text-white/40 hover:text-gold-300 hover:bg-gold-300/[0.06] transition-all duration-300"
          >
            <LogIn size={15} />
            <span className="text-xs">登录</span>
          </button>
        )}
      </div>
    </aside>
  )
}
