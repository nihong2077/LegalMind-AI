'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Scale, MessageSquare, FileText, LayoutDashboard, BookOpen, ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'

const navItems = [
  { name: '工作台', icon: LayoutDashboard, href: '/dashboard' },
  { name: 'AI 对话', icon: MessageSquare, href: '/chat' },
  { name: '文档分析', icon: FileText, href: '/documents' },
  { name: '法律知识库', icon: BookOpen, href: '/knowledge' },
]

export default function Sidebar() {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside
      className={`h-screen bg-navy-800/80 backdrop-blur-xl border-r border-gold-400/10
                  flex flex-col transition-all duration-300 ${collapsed ? 'w-20' : 'w-64'}`}
    >
      <div className="p-5 flex items-center gap-3 border-b border-gold-400/10">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-gold-400 to-gold-600 flex items-center justify-center flex-shrink-0">
          <Scale size={20} className="text-navy-900" />
        </div>
        {!collapsed && (
          <div className="animate-fade-in">
            <h1 className="text-lg font-bold text-gold-200">LegalMind</h1>
            <p className="text-[10px] text-gold-400/60 tracking-wider">AI 司法协作平台</p>
          </div>
        )}
      </div>

      <nav className="flex-1 p-3 space-y-1">
        {navItems.map(({ name, icon: Icon, href }) => {
          const isActive = pathname === href || pathname?.startsWith(href + '/')
          return (
            <Link
              key={href}
              href={href}
              className={isActive ? 'sidebar-link-active' : 'sidebar-link'}
            >
              <Icon size={18} className="flex-shrink-0" />
              {!collapsed && <span className="text-sm">{name}</span>}
            </Link>
          )
        })}
      </nav>

      <button
        onClick={() => setCollapsed(!collapsed)}
        className="m-3 p-2.5 rounded-lg border border-gold-400/15 text-gold-200/50
                   hover:text-gold-400 hover:border-gold-400/30 transition-all duration-200"
      >
        {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>
    </aside>
  )
}
