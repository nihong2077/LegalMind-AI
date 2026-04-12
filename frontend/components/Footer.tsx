'use client'

import { Scale } from 'lucide-react'
import Link from 'next/link'

export default function Footer() {
  return (
    <footer className="relative z-10 border-t border-gold-400/10 py-8 px-6">
      <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-gradient-to-br from-gold-400 to-gold-600 flex items-center justify-center">
            <Scale size={14} className="text-navy-900" />
          </div>
          <span className="text-sm text-gold-200/50">LegalMind AI — 面向民事法律场景的自适应司法协作多智能体系统</span>
        </div>
        <div className="flex items-center gap-6 text-xs text-gold-200/30">
          <Link href="/dashboard" className="hover:text-gold-200/60 transition-colors">工作台</Link>
          <Link href="/chat" className="hover:text-gold-200/60 transition-colors">AI 对话</Link>
          <Link href="/documents" className="hover:text-gold-200/60 transition-colors">文档分析</Link>
        </div>
      </div>
    </footer>
  )
}
