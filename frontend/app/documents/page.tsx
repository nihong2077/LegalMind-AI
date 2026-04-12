'use client'

import Sidebar from '@/components/Sidebar'
import DocumentUpload from '@/components/DocumentUpload'

export default function DocumentsPage() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-8">
        <DocumentUpload />
      </main>
    </div>
  )
}
