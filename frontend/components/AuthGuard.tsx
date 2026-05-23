'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { Loader2, Shield } from 'lucide-react'
import { isAuthenticated } from '@/app/lib/api'
import { useChatStore } from '@/store/useChatStore'

const PUBLIC_PATHS = ['/', '/login']

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { checkAuth } = useChatStore()
  const [checking, setChecking] = useState(true)
  const [authed, setAuthed] = useState(false)

  useEffect(() => {
    const authed = isAuthenticated()
    setAuthed(authed)
    checkAuth()  // 同步 Zustand store 状态

    if (!authed && !PUBLIC_PATHS.includes(pathname)) {
      router.replace('/login')
    }
    if (authed && pathname === '/login') {
      router.replace('/dashboard')
    }
    setChecking(false)
  }, [pathname, router, checkAuth])

  if (checking) {
    return (
      <div className="h-screen flex items-center justify-center bg-[#0a1628]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 size={32} className="animate-spin text-blue-400" />
          <p className="text-sm text-gold-200/40">验证身份中...</p>
        </div>
      </div>
    )
  }

  // 公开页面直接渲染
  if (PUBLIC_PATHS.includes(pathname)) {
    return <>{children}</>
  }

  // 需要登录的页面，未登录时不渲染内容
  if (!authed) {
    return (
      <div className="h-screen flex items-center justify-center bg-[#0a1628]">
        <div className="flex flex-col items-center gap-4">
          <Shield size={32} className="text-gold-200/30" />
          <p className="text-sm text-gold-200/40">请先登录</p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}