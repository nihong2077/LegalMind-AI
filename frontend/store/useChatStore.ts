import { create } from 'zustand'
import { chatStream, login, isAuthenticated, uploadDocument, analyzeDocument, type ChatMessage } from '@/app/lib/api'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  agent?: string
}

export interface Session {
  id: string
  title: string
  messages: Message[]
  createdAt: Date
  updatedAt: Date
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

export interface RightPanelData {
  quickQuestions: string[]
  relatedLaws: string[]
  riskWarnings: string[]
  termExplanations: { term: string; explanation: string }[]
  scenarioType: string
}

const LAW_KEYWORDS: Record<string, string[]> = {
  '租赁': ['《民法典》第七百零三条', '《民法典》第七百一十四条', '《民法典》第七百二十二条', '《民法典》第七百二十六条'],
  '押金': ['《民法典》第五百七十七条', '《民法典》第五百八十五条', '《民法典》第七百一十四条'],
  '劳动合同': ['《劳动合同法》第十条', '《劳动合同法》第四十六条', '《劳动合同法》第四十七条', '《劳动合同法》第八十二条'],
  '辞退': ['《劳动合同法》第三十九条', '《劳动合同法》第四十条', '《劳动合同法》第四十六条', '《劳动合同法》第四十七条'],
  '离婚': ['《民法典》第一千零七十六条', '《民法典》第一千零七十九条', '《民法典》第一千零八十七条'],
  '合同': ['《民法典》第四百六十九条', '《民法典》第五百零九条', '《民法典》第五百七十七条', '《民法典》第五百八十五条'],
  '侵权': ['《民法典》第一千一百六十五条', '《民法典》第一千一百七十九条', '《民法典》第一千一百八十三条'],
  '消费': ['《消费者权益保护法》第二十四条', '《消费者权益保护法》第五十五条', '《产品质量法》第四十条'],
  '工伤': ['《工伤保险条例》第十四条', '《工伤保险条例》第三十三条', '《工伤保险条例》第三十五条'],
  '欠薪': ['《劳动法》第五十条', '《劳动合同法》第三十条', '《劳动合同法》第八十五条'],
}

const RISK_KEYWORDS: Record<string, string[]> = {
  '租赁': ['注意诉讼时效——一般为3年，自权利人知道或应当知道权利受损之日起算', '保留好租赁合同原件及押金收据'],
  '押金': ['押金退还纠纷需在退房时及时主张权利', '注意区分押金与定金的法律性质'],
  '劳动合同': ['注意劳动仲裁前置程序——劳动争议需先仲裁再诉讼', '注意保留劳动关系证明材料'],
  '辞退': ['违法解除劳动合同可主张双倍经济补偿金', '注意收集辞退通知等书面证据'],
  '离婚': ['注意夫妻共同财产的认定范围', '注意子女抚养权的判定标准'],
  '合同': ['注意审查合同条款的效力', '注意违约金过高可请求法院调整'],
  '侵权': ['注意人身损害赔偿的诉讼时效为1年', '注意保存侵权行为的证据'],
  '消费': ['注意7天无理由退货的适用范围', '注意保留购物凭证和商品瑕疵证据'],
  '工伤': ['注意工伤认定的1年申请期限', '注意工伤认定需提供劳动关系证明'],
  '欠薪': ['注意劳动仲裁的时效为1年', '可向劳动监察部门投诉或申请支付令'],
}

const TERM_EXPLANATIONS: Record<string, { term: string; explanation: string }[]> = {
  '租赁': [
    { term: '押金', explanation: '承租人向出租人支付的担保金，租赁期满应予退还' },
    { term: '违约金', explanation: '合同一方违反约定时应向对方支付的赔偿金' },
  ],
  '劳动合同': [
    { term: '经济补偿金', explanation: '用人单位依法解除或终止劳动合同时支付给劳动者的补偿' },
    { term: '双倍工资', explanation: '未签书面劳动合同超过一个月的，应支付双倍工资' },
  ],
  '合同': [
    { term: '违约金', explanation: '合同一方违反约定时应向对方支付的赔偿金' },
    { term: '定金', explanation: '合同当事人一方在合同订立时预先给付对方的金钱，具有担保性质' },
  ],
  '消费': [
    { term: '惩罚性赔偿', explanation: '经营者欺诈行为应增加赔偿金额为价款的三倍' },
    { term: '无理由退货', explanation: '网购商品7天内可无理由退货（特殊商品除外）' },
  ],
}

const SCENARIO_KEYWORDS: Record<string, string> = {
  '租赁|押金|房东|租客|退房|房租': '租赁',
  '劳动合同|辞退|加班|社保|欠薪|工伤|解雇': '劳动',
  '合同|违约|解除|赔偿': '合同',
  '消费|网购|退货|质量|假货': '消费',
  '离婚|抚养|财产分割|家暴': '婚姻',
  '侵权|伤害|赔偿|医疗': '侵权',
}

function detectScenario(messages: Message[]): string {
  const allText = messages.map(m => m.content).join(' ')
  for (const [keywords, scenario] of Object.entries(SCENARIO_KEYWORDS)) {
    const kws = keywords.split('|')
    if (kws.some(kw => allText.includes(kw))) return scenario
  }
  return '通用'
}

function extractLawsFromContent(content: string): string[] {
  const lawPattern = /《[^》]+》第[一二三四五六七八九十百千零\d]+条/g
  const matches = content.match(lawPattern)
  return matches ? Array.from(new Set(matches)) : []
}

function buildRightPanelData(messages: Message[]): RightPanelData {
  const scenario = detectScenario(messages)
  const allText = messages.map(m => m.content).join(' ')
  const lawsFromContent = extractLawsFromContent(allText)

  const relatedLaws: string[] = [...lawsFromContent]
  for (const [keyword, laws] of Object.entries(LAW_KEYWORDS)) {
    if (allText.includes(keyword)) {
      for (const law of laws) {
        if (!relatedLaws.includes(law)) relatedLaws.push(law)
      }
    }
  }

  const riskWarnings: string[] = []
  for (const [keyword, risks] of Object.entries(RISK_KEYWORDS)) {
    if (allText.includes(keyword)) {
      riskWarnings.push(...risks)
    }
  }

  const termExplanations: { term: string; explanation: string }[] = []
  for (const [keyword, terms] of Object.entries(TERM_EXPLANATIONS)) {
    if (allText.includes(keyword)) {
      termExplanations.push(...terms)
    }
  }

  const quickQuestions: string[] = []
  const scenarioQuestions: Record<string, string[]> = {
    '租赁': ['押金不退', '租房纠纷', '提前解约', '维修责任', '转租问题', '租期届满'],
    '劳动': ['劳务争议', '辞退赔偿', '加班费', '社保补缴', '工伤认定', '欠薪追讨'],
    '合同': ['合同违约', '合同解除', '格式条款', '缔约过失', '不可抗力', '合同效力'],
    '消费': ['退货退款', '假货索赔', '虚假宣传', '质量纠纷', '服务违约', '网购维权'],
    '婚姻': ['离婚程序', '财产分割', '子女抚养', '家暴保护', '婚前财产', '协议离婚'],
    '侵权': ['人身损害', '医疗事故', '交通事故', '名誉侵权', '隐私侵权', '精神损害'],
    '通用': ['法律咨询', '诉讼流程', '证据收集', '时效问题', '管辖法院', '律师费'],
  }
  quickQuestions.push(...(scenarioQuestions[scenario] || scenarioQuestions['通用']))

  return {
    quickQuestions: Array.from(new Set(quickQuestions)).slice(0, 6),
    relatedLaws: Array.from(new Set(relatedLaws)).slice(0, 5),
    riskWarnings: Array.from(new Set(riskWarnings)).slice(0, 3),
    termExplanations: Array.from(new Set(termExplanations.map(t => JSON.stringify(t)))).map(t => JSON.parse(t)).slice(0, 4),
    scenarioType: scenario,
  }
}

const STORAGE_KEY = 'legalmind_sessions'
const CHAT_HISTORY_KEY = 'legalmind_chat_history'  // 供案件记忆页面使用
const MAX_CONTEXT_MESSAGES = 20

function loadSessions(): Session[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return parsed.map((s: Session) => ({
      ...s,
      messages: s.messages.map((m: Message) => ({ ...m, timestamp: new Date(m.timestamp) })),
      createdAt: new Date(s.createdAt),
      updatedAt: new Date(s.updatedAt),
    }))
  } catch {
    return []
  }
}

function saveSessions(sessions: Session[]) {
  if (typeof window === 'undefined') return
  try {
    const toSave = sessions.slice(0, 50)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave))
  } catch {
    // storage满时忽略
  }
}

interface ChatState {
  messages: Message[]
  currentCase: Case | null
  cases: Case[]
  documents: Document[]
  isStreaming: boolean
  sidebarCollapsed: boolean
  authed: boolean
  error: string | null
  abortController: AbortController | null

  sessions: Session[]
  currentSessionId: string | null
  rightPanelData: RightPanelData

  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void
  updateLastAssistantMessage: (content: string) => void
  clearMessages: () => void
  setIsStreaming: (streaming: boolean) => void
  setError: (error: string | null) => void
  setCurrentCase: (caseItem: Case | null) => void
  addCase: (caseItem: Omit<Case, 'id' | 'createdAt' | 'updatedAt'>) => void
  updateCaseStatus: (id: string, status: Case['status']) => void
  addDocument: (doc: Omit<Document, 'id' | 'uploadedAt'>) => void
  updateDocumentStatus: (id: string, status: Document['status']) => void
  toggleSidebar: () => void
  checkAuth: () => void
  setAuthed: (authed: boolean) => void
  loginUser: (username: string, password: string) => Promise<void>
  sendMessage: (content: string, model?: string) => Promise<void>
  stopStreaming: () => void

  createSession: () => string
  switchSession: (id: string) => void
  deleteSession: (id: string) => void
  saveCurrentSession: () => void

  uploadAndAnalyze: (file: File) => Promise<void>
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  currentCase: null,
  cases: [],
  documents: [],
  isStreaming: false,
  sidebarCollapsed: false,
  authed: false,
  error: null,
  abortController: null,

  sessions: loadSessions(),
  currentSessionId: null,
  rightPanelData: {
    quickQuestions: ['法律咨询', '诉讼流程', '证据收集', '时效问题', '管辖法院', '律师费'],
    relatedLaws: [],
    riskWarnings: [],
    termExplanations: [],
    scenarioType: '通用',
  },

  addMessage: (message) =>
    set((state) => {
      const newMsg: Message = {
        ...message,
        id: Date.now().toString() + Math.random().toString(36).slice(2),
        timestamp: new Date(),
      }
      const newMessages = [...state.messages, newMsg]
      const rightPanelData = buildRightPanelData(newMessages)
      return { messages: newMessages, rightPanelData }
    }),

  updateLastAssistantMessage: (content) =>
    set((state) => {
      const msgs = [...state.messages]
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'assistant') {
          msgs[i] = { ...msgs[i], content }
          break
        }
      }
      const rightPanelData = buildRightPanelData(msgs)
      return { messages: msgs, rightPanelData }
    }),

  clearMessages: () =>
    set({
      messages: [],
      rightPanelData: {
        quickQuestions: ['法律咨询', '诉讼流程', '证据收集', '时效问题', '管辖法院', '律师费'],
        relatedLaws: [],
        riskWarnings: [],
        termExplanations: [],
        scenarioType: '通用',
      },
    }),

  setIsStreaming: (streaming) => set({ isStreaming: streaming }),

  setError: (error) => set({ error }),

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

  checkAuth: () => set({ authed: isAuthenticated() }),

  setAuthed: (authed) => set({ authed }),

  loginUser: async (username, password) => {
    try {
      await login(username, password)
      set({ authed: true, error: null })
    } catch (e) {
      set({ error: (e as Error).message })
      throw e
    }
  },

  sendMessage: async (content, model = 'deepseek-flash') => {
    const state = get()

    if (state.isStreaming) return
    if (!state.authed) {
      set({ error: '请先登录' })
      return
    }

    if (!state.currentSessionId) {
      get().createSession()
    }

    get().addMessage({ role: 'user', content })

    get().addMessage({ role: 'assistant', content: '', agent: 'LegalMind AI' })

    const abortController = new AbortController()
    set({ isStreaming: true, error: null, abortController })

    const recentMessages = state.messages
      .filter((m) => m.role !== 'system')
      .slice(-MAX_CONTEXT_MESSAGES)

    const chatMessages: ChatMessage[] = recentMessages.map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
    }))
    chatMessages.push({ role: 'user', content })

    let fullContent = ''

    try {
      for await (const event of chatStream(chatMessages, model, abortController.signal)) {
        if (event.type === 'chunk') {
          const chunk = event.data as { content: string; role: string }
          fullContent += chunk.content
          get().updateLastAssistantMessage(fullContent)
        } else if (event.type === 'done') {
          const done = event.data as { content: string; role: string; finish_reason: string }
          if (done.content) {
            fullContent = done.content
            get().updateLastAssistantMessage(fullContent)
          }
          get().saveCurrentSession()
        } else if (event.type === 'error') {
          const err = event.data as { error: string; message: string }
          get().updateLastAssistantMessage(`⚠️ ${err.message || 'AI 服务暂时不可用'}`)
          set({ error: err.message })
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        get().updateLastAssistantMessage('⚠️ 连接中断，请重试')
        set({ error: (e as Error).message })
      }
    } finally {
      set({ isStreaming: false, abortController: null })
      get().saveCurrentSession()
    }
  },

  stopStreaming: () => {
    const { abortController } = get()
    if (abortController) {
      abortController.abort()
      set({ isStreaming: false, abortController: null })
    }
  },

  createSession: () => {
    const id = Date.now().toString() + Math.random().toString(36).slice(2)
    const session: Session = {
      id,
      title: '新对话',
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date(),
    }
    set((state) => {
      const sessions = [session, ...state.sessions]
      saveSessions(sessions)
      return {
        sessions,
        currentSessionId: id,
        messages: [],
        rightPanelData: {
          quickQuestions: ['法律咨询', '诉讼流程', '证据收集', '时效问题', '管辖法院', '律师费'],
          relatedLaws: [],
          riskWarnings: [],
          termExplanations: [],
          scenarioType: '通用',
        },
      }
    })
    return id
  },

  switchSession: (id) => {
    const state = get()
    get().saveCurrentSession()
    const session = state.sessions.find((s) => s.id === id)
    if (session) {
      const rightPanelData = buildRightPanelData(session.messages)
      set({
        currentSessionId: id,
        messages: session.messages,
        rightPanelData,
      })
    }
  },

  deleteSession: (id) => {
    set((state) => {
      const sessions = state.sessions.filter((s) => s.id !== id)
      saveSessions(sessions)

      // 同步删除案件记忆
      if (typeof window !== 'undefined') {
        try {
          const raw = localStorage.getItem(CHAT_HISTORY_KEY)
          const histories = raw ? JSON.parse(raw) : []
          localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(histories.filter((h: { id: string }) => h.id !== id)))
        } catch { /* storage full */ }
      }

      if (state.currentSessionId === id) {
        const newCurrent = sessions[0]?.id || null
        const newMessages = sessions[0]?.messages || []
        const rightPanelData = buildRightPanelData(newMessages)
        return {
          sessions,
          currentSessionId: newCurrent,
          messages: newMessages,
          rightPanelData,
        }
      }
      return { sessions }
    })
  },

  saveCurrentSession: () => {
    set((state) => {
      if (!state.currentSessionId) return state
      const firstUserMsg = state.messages.find((m) => m.role === 'user')
      const title = firstUserMsg
        ? firstUserMsg.content.slice(0, 20) + (firstUserMsg.content.length > 20 ? '...' : '')
        : '新对话'

      const sessions = state.sessions.map((s) =>
        s.id === state.currentSessionId
          ? { ...s, title, messages: state.messages, updatedAt: new Date() }
          : s
      )

      const currentSession = sessions.find((s) => s.id === state.currentSessionId)
      if (!currentSession) {
        const newSession: Session = {
          id: state.currentSessionId,
          title,
          messages: state.messages,
          createdAt: new Date(),
          updatedAt: new Date(),
        }
        sessions.unshift(newSession)
      }

      saveSessions(sessions)

      // 同步保存到案件记忆存储
      if (typeof window !== 'undefined' && state.messages.length > 0) {
        try {
          const raw = localStorage.getItem(CHAT_HISTORY_KEY)
          const histories = raw ? JSON.parse(raw) : []
          const existing = histories.findIndex((h: { id: string }) => h.id === state.currentSessionId)
          const entry = {
            id: state.currentSessionId,
            title,
            messages: state.messages.map(m => ({ role: m.role, content: m.content, timestamp: m.timestamp.toISOString() })),
            createdAt: new Date().toISOString(),
          }
          if (existing >= 0) histories[existing] = entry
          else histories.unshift(entry)
          localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(histories.slice(0, 50)))
        } catch { /* storage full */ }
      }

      return { sessions }
    })
  },

  uploadAndAnalyze: async (file) => {
    const state = get()
    if (!state.authed) {
      set({ error: '请先登录' })
      return
    }

    const docId = Date.now().toString() + Math.random().toString(36).slice(2)
    get().addDocument({
      name: file.name,
      size: `${(file.size / 1024).toFixed(1)} KB`,
      type: file.name.split('.').pop()?.toUpperCase() || 'FILE',
      status: 'uploading',
    })

    try {
      get().updateDocumentStatus(docId, 'uploading')
      const result = await uploadDocument(file)
      get().updateDocumentStatus(docId, 'analyzing')

      const analysisResult = await analyzeDocument(result.id)
      get().addMessage({
        role: 'assistant',
        content: `📄 已上传文档「${file.name}」，正在分析中...\n\n任务ID: ${analysisResult.task_id}`,
        agent: 'LegalMind AI',
      })
      get().saveCurrentSession()
    } catch (e) {
      get().updateDocumentStatus(docId, 'error')
      set({ error: `文档上传失败: ${(e as Error).message}` })
    }
  },
}))
