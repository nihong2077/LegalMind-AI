'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { Loader2, Shield } from 'lucide-react'
import { isAuthenticated } from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

const PUBLIC_PATHS = ['/', '/login']

// 已并入消息中心的旧页面：从导航隐藏，且直接访问时重定向到 /messages
const MERGED_PATHS = ['/chat', '/court', '/dashboard']

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { checkAuth } = useChatStore()
  const [checking, setChecking] = useState(true)
  const [authed, setAuthed] = useState(false)

  useEffect(() => {
    const authed = isAuthenticated()
    setAuthed(authed)
    checkAuth()

    if (!authed && !PUBLIC_PATHS.includes(pathname)) {
      router.replace('/login')
    }
    if (authed && pathname === '/login') {
      router.replace('/messages')
    }
    // 旧路由（已并入消息中心）直达时重定向，避免绕过新 IA
    if (authed && MERGED_PATHS.some((p) => pathname === p || pathname?.startsWith(p + '/'))) {
      router.replace('/messages')
    }
    // /cases 已由记忆模块的「案件视图」取代（T2.4）
    if (authed && pathname === '/cases') {
      router.replace('/memory?view=cases')
    }
    // /knowledge 已收编为搜索页的「知识库浏览」次级入口（T3.2）
    if (authed && pathname === '/knowledge') {
      router.replace('/search')
    }
    setChecking(false)
  }, [pathname, router, checkAuth])

  if (checking) {
    return (
      <div className="h-screen flex items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-4">
          <Loader2 size={32} className="animate-spin text-blue-600" />
          <p className="text-sm text-slate-500">验证身份中...</p>
        </div>
      </div>
    )
  }

  if (PUBLIC_PATHS.includes(pathname)) {
    return <>{children}</>
  }

  if (!authed) {
    return (
      <div className="h-screen flex items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-4">
          <Shield size={32} className="text-slate-300" />
          <p className="text-sm text-slate-500">请先登录</p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
