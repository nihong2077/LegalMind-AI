'use client'

import Sidebar from '@/components/Sidebar'
import ChatInterface from '@/components/ChatInterface'

export default function ChatPage() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-0">
        <div className="px-6 py-4 border-b border-gold-400/10 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gold-200">AI 法律对话</h2>
            <p className="text-xs text-gold-200/40">多智能体协同分析，为您提供专业法律建议</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
            <span className="text-xs text-gold-200/50">在线</span>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          <ChatInterface />
        </div>
      </main>
    </div>
  )
}
