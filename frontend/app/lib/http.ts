/**
 * 统一 HTTP 客户端（T0.12，Harness §7.1 前端侧）
 *
 * - 自动注入 Authorization、JSON 序列化（FormData 透传）
 * - 统一解包 ApiResponse 信封：成功返回 data，失败抛 ApiError（code/retryable/requestId）
 * - 401：清凭证并跳登录页（浏览器侧）
 * - 429 / 502 / 503 / 504：遵守 Retry-After 的指数退避自动重试
 *   （仅幂等方法 GET/HEAD/PUT/DELETE 或带 Idempotency-Key 的请求）
 * - 网络错误：幂等请求同样自动重试
 *
 * SSE 流请用 requestRaw（拿到原始 Response 后自行解析），不做重试。
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// 用户名键保持全局（用于识别「当前是谁」）；Token 键按用户名隔离，避免多账号串号
const USERNAME_KEY = 'legalmind_username'
const TOKEN_BASE = 'legalmind_token'

// ---------------- 凭证 ----------------

/** Token 存储键：`legalmind_token:{username}`；无用户名视为未登录（返回 null） */
function tokenStorageKey(username?: string | null): string | null {
  const user = username ?? getUsername()
  return user ? `${TOKEN_BASE}:${user}` : null
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  const key = tokenStorageKey()
  return key ? localStorage.getItem(key) : null
}

/**
 * 写入 Token。用户名未提供时回退到当前登录用户名；
 * 二者皆无则忽略（未登录态不应写凭证）。
 */
export function setToken(token: string, username?: string): void {
  if (typeof window === 'undefined') return
  const key = tokenStorageKey(username)
  if (!key) return
  localStorage.setItem(key, token)
}

export function setUsername(username: string): void {
  localStorage.setItem(USERNAME_KEY, username)
}

export function clearToken(): void {
  if (typeof window === 'undefined') return
  // 先按当前用户名定位隔离 Token 键并删除，再清用户名
  const key = tokenStorageKey()
  if (key) localStorage.removeItem(key)
  localStorage.removeItem(USERNAME_KEY)
  // 清理历史遗留的全局 Token 键（隔离改造前的遗留凭证）
  localStorage.removeItem(TOKEN_BASE)
}

export function isAuthenticated(): boolean {
  return !!getToken()
}

export function getUsername(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(USERNAME_KEY)
}

// ---------------- 错误 ----------------

export class ApiError extends Error {
  code: number
  status: number
  retryable: boolean
  requestId?: string
  detail?: unknown

  constructor(
    code: number,
    status: number,
    message: string,
    retryable: boolean,
    requestId?: string,
    detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.retryable = retryable
    this.requestId = requestId
    this.detail = detail
  }
}

/**
 * 前端本地错误码：请求在到达服务端前就失败（后端不可达 / DNS 失败 / CORS 拦截）。
 * 这类失败没有服务端信封，后端永远不会下发 50001，前端仅用于兜底文案与重试判定。
 */
export const NETWORK_ERROR_CODE = 50001

/**
 * fetch 层网络故障统一转成 ApiError。
 * 浏览器对这类失败只给裸英文 "Failed to fetch"，直接上屏对用户不可读，故在此收口为中文提示。
 * 调用方主动取消（AbortError）由各调用处原样抛出，不经过此处，避免改变取消语义。
 */
function toNetworkError(cause: unknown): ApiError {
  return new ApiError(
    NETWORK_ERROR_CODE,
    0,
    '无法连接后端服务，请检查网络或稍后重试',
    true,
    undefined,
    cause,
  )
}

/** 信封失败体（与后端 core/response.py 对齐） */
interface ErrorEnvelope {
  code: number
  message: string
  detail?: unknown
  retryable?: boolean
  request_id?: string
}

interface ApiEnvelope<T> extends ErrorEnvelope {
  data: T
}

export interface HttpInit {
  method?: string
  headers?: Record<string, string>
  body?: BodyInit | object
  signal?: AbortSignal
  /** 最大尝试次数（含首发），默认 3；非幂等请求强制 1 */
  maxAttempts?: number
}

const RETRY_STATUSES = new Set([429, 502, 503, 504])
const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE'])

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function buildHeaders(init: HttpInit, hasToken: boolean): Record<string, string> {
  const headers: Record<string, string> = {
    ...(init.headers || {}),
  }
  if (hasToken) headers['Authorization'] = `Bearer ${getToken()}`
  return headers
}

function isIdempotent(init: HttpInit): boolean {
  const method = (init.method || 'GET').toUpperCase()
  if (IDEMPOTENT_METHODS.has(method)) return true
  const hdrs = init.headers || {}
  return Object.keys(hdrs).some((k) => k.toLowerCase() === 'idempotency-key')
}

function handleUnauthorized(): void {
  clearToken()
  if (typeof window !== 'undefined') {
    window.location.href = '/login'
  }
}

/**
 * 401 处理：仅当本地持有失效 Token（会话过期）时才清凭证并跳登录页；
 * 登录接口本身的 401（用户名/密码错误）不跳转，保留服务端消息供页面展示。
 */
async function unauthorizedError(res: Response): Promise<ApiError> {
  const parsed = await readJsonSafely(res).catch(() => null)
  const error = toApiError(401, parsed)
  if (getToken()) {
    handleUnauthorized()
  }
  return error
}

function backoffDelay(attempt: number, retryAfter: string | null): number {
  if (retryAfter) {
    const secs = Number.parseFloat(retryAfter)
    if (Number.isFinite(secs) && secs >= 0) {
      return Math.min(secs * 1000, 10_000)
    }
  }
  // 0.5s → 1s（+25% 抖动），与后端 tenacity 退避风格一致
  const base = 500 * 2 ** attempt
  return Math.min(base * (0.75 + Math.random() * 0.5), 8_000)
}

function toApiError(status: number, body: unknown): ApiError {
  if (body && typeof body === 'object' && 'code' in body) {
    const e = body as ErrorEnvelope
    return new ApiError(
      e.code,
      status,
      e.message || '请求失败',
      e.retryable ?? RETRY_STATUSES.has(status),
      e.request_id,
      e.detail,
    )
  }
  // 兜底：非信封形状 {"detail":...}（历史响应，兼容保留）
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : '请求失败'
  const fallbackCode =
    status === 401 ? 40101
    : status === 403 ? 40301
    : status === 404 ? 40004
    : status === 409 ? 40009
    : status === 429 ? 42901
    : status >= 500 ? 50000
    : 40001
  return new ApiError(fallbackCode, status, detail || '请求失败', RETRY_STATUSES.has(status))
}

async function readJsonSafely(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/**
 * 发起 JSON 请求并解包信封，成功直接返回 data。
 * 失败（信封 code!=0 / !res.ok）抛 ApiError；401 会跳登录页。
 */
export async function request<T = unknown>(
  path: string,
  init: HttpInit = {},
): Promise<T> {
  const method = (init.method || 'GET').toUpperCase()
  const idempotent = isIdempotent(init)
  const maxAttempts = idempotent ? (init.maxAttempts ?? 3) : 1
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`

  let lastError: unknown
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const headers = buildHeaders(init, !!getToken())
    let body: BodyInit | undefined
    if (init.body !== undefined) {
      if (init.body instanceof FormData || typeof init.body === 'string') {
        body = init.body
      } else {
        headers['Content-Type'] = headers['Content-Type'] || 'application/json'
        body = JSON.stringify(init.body)
      }
    }

    let res: Response
    try {
      res = await fetch(url, { method, headers, body, signal: init.signal })
    } catch (e) {
      lastError = e
      const aborted = e instanceof DOMException && e.name === 'AbortError'
      if (idempotent && attempt < maxAttempts - 1 && !aborted) {
        await sleep(backoffDelay(attempt, null))
        continue
      }
      if (aborted) throw e
      throw toNetworkError(e)
    }

    if (res.status === 401) {
      throw await unauthorizedError(res)
    }

    if (RETRY_STATUSES.has(res.status) && idempotent && attempt < maxAttempts - 1) {
      res.body?.cancel().catch(() => {})
      await sleep(backoffDelay(attempt, res.headers.get('Retry-After')))
      continue
    }

    const parsed = await readJsonSafely(res)

    if (!res.ok) {
      throw toApiError(res.status, parsed)
    }

    if (parsed && typeof parsed === 'object' && 'code' in parsed) {
      const envelope = parsed as ApiEnvelope<T>
      if (envelope.code !== 0) {
        throw new ApiError(
          envelope.code,
          res.status,
          envelope.message || '请求失败',
          envelope.retryable ?? false,
          envelope.request_id,
          envelope.detail,
        )
      }
      return envelope.data
    }

    // 非信封响应（历史响应，兼容保留）：原样返回
    return parsed as T
  }

  // 循环正常结束只可能来自网络失败分支（重试条件均带 attempt < maxAttempts - 1 守卫），
  // 故此处统一按网络故障收口。
  throw toNetworkError(lastError)
}

/**
 * 发起请求但不解包：用于 SSE 流式响应。
 * 401 仍会清凭证跳转；非 2xx 会读取信封错误并抛 ApiError。
 * 不做重试（流不可安全重放，由调用方控制重连）。
 */
export async function requestRaw(
  path: string,
  init: HttpInit = {},
): Promise<Response> {
  const method = (init.method || 'GET').toUpperCase()
  const headers = buildHeaders(init, !!getToken())
  let body: BodyInit | undefined
  if (init.body !== undefined) {
    if (init.body instanceof FormData || typeof init.body === 'string') {
      body = init.body
    } else {
      headers['Content-Type'] = headers['Content-Type'] || 'application/json'
      body = JSON.stringify(init.body)
    }
  }

  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  let res: Response
  try {
    res = await fetch(url, { method, headers, body, signal: init.signal })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw toNetworkError(e)
  }

  if (res.status === 401) {
    throw await unauthorizedError(res)
  }

  if (!res.ok) {
    const parsed = await readJsonSafely(res)
    throw toApiError(res.status, parsed)
  }

  return res
}
