'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { Loader2, Shield } from 'lucide-react'
import { isAuthenticated } from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

const PUBLIC_PATHS = ['/', '/login']

// 旧路由 → 新 IA 映射（T4.1）：服务端权威重定向见 next.config.js；
// 此处保留为客户端导航兜底（旧页面文件已物理删除）。
const LEGACY_ROUTE_MAP: Record<string, string> = {
  '/chat': '/messages',
  '/court': '/messages?template=court',
  '/dashboard': '/messages',
  '/knowledge': '/search',
  '/cases': '/memory?view=cases',
}

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
    // 旧路由（已并入新 IA）直达时重定向，避免绕过新导航
    const legacyTarget = LEGACY_ROUTE_MAP[pathname ?? '']
    if (authed && legacyTarget) {
      router.replace(legacyTarget)
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
