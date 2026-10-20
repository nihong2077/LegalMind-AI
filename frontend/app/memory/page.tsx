'use client'

/**
 * 记忆模块页（T2.4）
 * 三栏 IA：图标栏 ｜ 记忆列表 ｜ 详情栏；
 * `?view=cases` 时切换为「案件视图」（协同群聊 + 合同审查），替代旧 /cases。
 */
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import IconRail from '@/components/collab/IconRail'
import MemoryList from '@/components/memory/MemoryList'
import MemoryDetail from '@/components/memory/MemoryDetail'
import MemoryEditor from '@/components/memory/MemoryEditor'
import CasesPane from '@/components/memory/CasesPane'
import { useMemoryStore } from '@/store/useMemoryStore'

function MemoryPageInner() {
  const searchParams = useSearchParams()
  const isCasesView = searchParams.get('view') === 'cases'
  const fetchSetting = useMemoryStore((s) => s.fetchSetting)
  const [editorOpen, setEditorOpen] = useState(false)

  useEffect(() => {
    fetchSetting()
  }, [fetchSetting])

  return (
    <div className="flex h-screen overflow-hidden">
      <IconRail />
      {isCasesView ? (
        <CasesPane />
      ) : (
        <>
          <MemoryList onNewMemory={() => setEditorOpen(true)} />
          <MemoryDetail />
          <MemoryEditor open={editorOpen} onClose={() => setEditorOpen(false)} />
        </>
      )}
    </div>
  )
}

export default function MemoryPage() {
  return (
    <Suspense
      fallback={
        <div className="h-screen flex items-center justify-center text-sm text-slate-400">
          加载中...
        </div>
      }
    >
      <MemoryPageInner />
    </Suspense>
  )
}
