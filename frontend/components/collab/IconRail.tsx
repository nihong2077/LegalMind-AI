'use client'

/**
 * 消息中心图标栏（微信式最左列，T1.8-M1）
 * 仅图标 + 原生 tooltip，承载全局导航与当前用户。
 */
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  Brain,
  FileText,
  LogOut,
  MessagesSquare,
  Search,
  Shield,
  User,
} from 'lucide-react'
import { clearToken, getUsername } from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

const railItems = [
  { name: '消息中心', icon: MessagesSquare, href: '/messages' },
  { name: '案情搜索', icon: Search, href: '/search' },
  { name: '记忆', icon: Brain, href: '/memory' },
  { name: '合同审查', icon: FileText, href: '/documents' },
]

export default function IconRail() {
  const pathname = usePathname()
  const router = useRouter()
  const setAuthed = useChatStore((s) => s.setAuthed)
  const [username, setUsername] = useState<string | null>(null)

  useEffect(() => {
    setUsername(getUsername())
  }, [])

  const handleLogout = () => {
    clearToken()
    setAuthed(false)
    router.replace('/login')
  }

  return (
    <aside className="w-16 h-screen bg-[#152c4a] flex flex-col items-center border-r border-white/10 flex-shrink-0">
      <Link
        href="/"
        title="智法 AI"
        className="w-full h-14 flex items-center justify-center border-b border-white/10 hover:bg-white/5 transition-colors"
      >
        <div className="w-9 h-9 rounded-lg bg-blue-500 flex items-center justify-center">
          <Shield size={18} className="text-white" />
        </div>
      </Link>

      <nav className="flex-1 w-full py-3 space-y-1">
        {railItems.map(({ name, icon: Icon, href }) => {
          const isActive = pathname === href || pathname?.startsWith(href + '/')
          return (
            <Link
              key={href}
              href={href}
              title={name}
              className={`mx-auto w-10 h-10 flex items-center justify-center rounded-lg transition-all duration-200 ${
                isActive
                  ? 'bg-white/15 text-white border border-white/10'
                  : 'text-white/60 hover:text-white hover:bg-white/10'
              }`}
            >
              <Icon size={19} />
            </Link>
          )
        })}
      </nav>

      <div className="w-full py-3 border-t border-white/10 flex flex-col items-center gap-3">
        <div
          title={username || '未登录'}
          className="w-9 h-9 rounded-full bg-blue-500/30 border border-blue-300/30 flex items-center justify-center"
        >
          <User size={15} className="text-blue-200" />
        </div>
        <button
          onClick={handleLogout}
          title="退出登录"
          className="w-10 h-10 flex items-center justify-center rounded-lg text-white/50 hover:text-red-300 hover:bg-white/10 transition-colors"
        >
          <LogOut size={16} />
        </button>
      </div>
    </aside>
  )
}
