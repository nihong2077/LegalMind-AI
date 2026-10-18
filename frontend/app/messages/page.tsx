'use client'

/**
 * 消息中心（T1.8-M1）：微信式三栏 IA 外壳
 * 图标栏 ｜ 会话列表 ｜ 聊天区 ｜ 可折叠右栏
 *
 * 数据：GET /api/conversations、GET /api/agents、GET /api/agents/templates。
 * 流式对话（M2）已接入；建群向导（M3）由 ConversationList 的「+」唤起；
 * 接管与时间线（M4）在后续里程碑接入。
 */
import { useEffect, useState } from 'react'
import IconRail from '@/components/collab/IconRail'
import ConversationList from '@/components/collab/ConversationList'
import ChatArea from '@/components/collab/ChatArea'
import RightRail from '@/components/collab/RightRail'
import NewConversationWizard from '@/components/collab/NewConversationWizard'
import { useCollabStore } from '@/store/useCollabStore'

export default function MessagesPage() {
  const fetchConversations = useCollabStore((s) => s.fetchConversations)
  const fetchCatalog = useCollabStore((s) => s.fetchCatalog)
  const [wizardOpen, setWizardOpen] = useState(false)

  useEffect(() => {
    fetchConversations()
    fetchCatalog()
  }, [fetchConversations, fetchCatalog])

  return (
    <div className="flex h-screen overflow-hidden">
      <IconRail />
      <ConversationList onNewConversation={() => setWizardOpen(true)} />
      <ChatArea />
      <RightRail />
      <NewConversationWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
    </div>
  )
}
