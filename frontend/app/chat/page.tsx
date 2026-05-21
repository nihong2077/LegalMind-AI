'use client'

import { useState } from 'react'
import Sidebar from '@/components/Sidebar'
import ChatInterface from '@/components/ChatInterface'
import RightPanel from '@/components/RightPanel'
import LoginModal from '@/components/LoginModal'
import { useChatStore } from '@/store/useChatStore'

export default function ChatPage() {
  const sendMessage = useChatStore((s) => s.sendMessage)
  const [showLoginModal, setShowLoginModal] = useState(false)

  const handleQuickQuestionClick = (question: string) => {
    sendMessage(question)
  }

  return (
    <div className="flex h-screen">
      <Sidebar onLoginClick={() => setShowLoginModal(true)} />
      <main className="flex-1 flex flex-col min-h-0">
        <ChatInterface />
      </main>
      <RightPanel onQuickQuestionClick={handleQuickQuestionClick} />
      <LoginModal isOpen={showLoginModal} onClose={() => setShowLoginModal(false)} onLoginSuccess={() => setShowLoginModal(false)} />
    </div>
  )
}
