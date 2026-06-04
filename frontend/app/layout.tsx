import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import AuthGuard from '@/components/AuthGuard'

const inter = Inter({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700', '800'],
  display: 'swap',
  variable: '--font-inter',
})

export const metadata: Metadata = {
  title: 'LegalMind AI - 智能司法协作平台',
  description: '面向民事法律场景的自适应司法协作多智能体系统',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN" className={inter.variable}>
      <body className="min-h-screen antialiased font-[family-name:var(--font-inter)]">
        <AuthGuard>
          {children}
        </AuthGuard>
      </body>
    </html>
  )
}