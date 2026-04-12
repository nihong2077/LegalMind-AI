import { create } from 'zustand'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  agent?: string
}

export interface Case {
  id: string
  title: string
  description: string
  status: 'pending' | 'analyzing' | 'ready' | 'closed'
  createdAt: Date
  updatedAt: Date
}

export interface Document {
  id: string
  name: string
  size: string
  type: string
  status: 'uploading' | 'analyzing' | 'ready' | 'error'
  uploadedAt: Date
}

interface ChatState {
  messages: Message[]
  currentCase: Case | null
  cases: Case[]
  documents: Document[]
  isTyping: boolean
  sidebarCollapsed: boolean

  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void
  clearMessages: () => void
  setIsTyping: (typing: boolean) => void
  setCurrentCase: (caseItem: Case | null) => void
  addCase: (caseItem: Omit<Case, 'id' | 'createdAt' | 'updatedAt'>) => void
  updateCaseStatus: (id: string, status: Case['status']) => void
  addDocument: (doc: Omit<Document, 'id' | 'uploadedAt'>) => void
  updateDocumentStatus: (id: string, status: Document['status']) => void
  toggleSidebar: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  currentCase: null,
  cases: [],
  documents: [],
  isTyping: false,
  sidebarCollapsed: false,

  addMessage: (message) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          ...message,
          id: Date.now().toString() + Math.random().toString(36).slice(2),
          timestamp: new Date(),
        },
      ],
    })),

  clearMessages: () => set({ messages: [] }),

  setIsTyping: (typing) => set({ isTyping: typing }),

  setCurrentCase: (caseItem) => set({ currentCase: caseItem }),

  addCase: (caseItem) =>
    set((state) => ({
      cases: [
        ...state.cases,
        {
          ...caseItem,
          id: Date.now().toString(),
          createdAt: new Date(),
          updatedAt: new Date(),
        },
      ],
    })),

  updateCaseStatus: (id, status) =>
    set((state) => ({
      cases: state.cases.map((c) =>
        c.id === id ? { ...c, status, updatedAt: new Date() } : c
      ),
    })),

  addDocument: (doc) =>
    set((state) => ({
      documents: [
        ...state.documents,
        {
          ...doc,
          id: Date.now().toString() + Math.random().toString(36).slice(2),
          uploadedAt: new Date(),
        },
      ],
    })),

  updateDocumentStatus: (id, status) =>
    set((state) => ({
      documents: state.documents.map((d) => (d.id === id ? { ...d, status } : d)),
    })),

  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}))
