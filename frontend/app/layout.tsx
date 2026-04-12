import type { Metadata } from 'next'
import './globals.css'

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
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">
        {children}
      </body>
    </html>
  )
}
