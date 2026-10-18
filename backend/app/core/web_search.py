"""DeepSeek 官方联网检索客户端（Search + Fetch，P2-WebSearch Step1）

对齐 DeepSeek 官方文档 <https://api-docs.deepseek.com/zh-cn/guides/search>：

- ``POST /v1/tools/search``：联网搜索，返回结构化结果
  （``title/url/snippet/summary/content/site_name/date/authority/rerank_score``）；
- ``POST /v1/tools/fetch``：抓取指定 URL 正文（Markdown，``title/content``）。

**路由策略（透传优先 + 直连回退）**：

1. 优先经 **LiteLLM 代理**（``litellm/config.yaml`` 的 ``pass_through_endpoints``）以
   **虚拟 key** 调用——DeepSeek 真实 key 由代理侧注入（``os.environ/DEEPSEEK_API_KEY``），
   后端全程不接触真实 key，遵守密钥隔离约束；
2. LiteLLM 未启动 / 未配置 / 透传失败时，回退为以 ``DEEPSEEK_API_KEY`` **直连**
   ``api.deepseek.com``，保证本地开发（LiteLLM 常未运行）仍可用。

**失败语义**：可重试错误（408/429/5xx 与连接/超时）在同一条链路上按
``WEB_SEARCH_MAX_ATTEMPTS`` 重试；重试耗尽或链路不可用则换下一条链路；
两条链路都失败才抛 :class:`WebSearchError`。**明确客户端错误（4xx，除 408/429）不重试也不回退**，
避免遮蔽真实参数/鉴权问题。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from .config import settings
from .metrics import WEB_SEARCH_CALLS

logger = logging.getLogger(__name__)

# DeepSeek 官方 API 根（search/fetch 与 chat 同域）
DEEPSEEK_API_BASE = "https://api.deepseek.com"
SEARCH_PATH = "/v1/tools/search"
FETCH_PATH = "/v1/tools/fetch"

# 文档口径：query 1-128 字符、ori_question ≤128、count 1-50、url ≤8192
QUERY_MAX_LEN = 128
ORI_QUESTION_MAX_LEN = 128
COUNT_MIN, COUNT_MAX = 1, 50
URL_MAX_LEN = 8192

# 可重试状态码（对齐文档：408/429/5xx 可重试）
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# 链路标记（指标 label：proxy=透传 / direct=直连）
MODE_PROXY = "proxy"
MODE_DIRECT = "direct"


class WebSearchError(RuntimeError):
    """联网检索最终失败（两条链路均不可用 / 重试耗尽）。"""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _build_query(query: str, site: Optional[str]) -> str:
    """校验/规范化检索词：去空白、限 128 字，可选注入 ``site:`` 限定域名。"""
    q = str(query or "").strip()
    if not q:
        raise ValueError("query 不能为空")
    if site:
        site = str(site).strip()
        if site and not q.lower().startswith("site:"):
            q = f"site:{site} {q}"
    return _truncate(q, QUERY_MAX_LEN)


def _clamp_count(count: Optional[int]) -> int:
    if count is None:
        return int(settings.WEB_SEARCH_COUNT)
    try:
        value = int(count)
    except (TypeError, ValueError):
        return int(settings.WEB_SEARCH_COUNT)
    return max(COUNT_MIN, min(COUNT_MAX, value))


def _error_message(response: httpx.Response) -> str:
    """解析 OpenAI 兼容错误体 ``{error:{message,...}}``，退化到原文。"""
    try:
        detail = response.json().get("error") or {}
        msg = detail.get("message") or response.text
    except Exception:  # 非 JSON 错误体：直接取文本
        msg = response.text
    return f"HTTP {response.status_code}: {msg}"


def normalize_search_result(raw: dict[str, Any]) -> dict[str, Any]:
    """把官方返回条目规范为稳定内部结构。

    ``content`` 在 ``need_content=false`` 时为空，故按 ``content → summary → snippet``
    逐级回退，保证下游「资料块/引用卡」始终有可读正文。
    """
    content = raw.get("content") or raw.get("summary") or raw.get("snippet") or ""
    return {
        "title": str(raw.get("title") or ""),
        "url": str(raw.get("url") or ""),
        "snippet": str(raw.get("snippet") or ""),
        "summary": str(raw.get("summary") or ""),
        "content": str(content),
        "site_name": str(raw.get("site_name") or ""),
        "date": raw.get("date") or "",
        "authority": raw.get("authority"),
        "rerank_score": raw.get("rerank_score"),
    }


class WebSearchClient:
    """联网检索客户端（Search/Fetch）。测试可注入 ``proxy_client`` / ``direct_client``。"""

    def __init__(
        self,
        *,
        proxy_url: Optional[str] = None,
        virtual_key: Optional[str] = None,
        deepseek_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_attempts: Optional[int] = None,
        retry_backoff: float = 0.5,
        proxy_client: Optional[httpx.AsyncClient] = None,
        direct_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.proxy_url = (proxy_url or settings.LITELLM_PROXY_URL).rstrip("/")
        self.virtual_key = virtual_key or settings.LITELLM_VIRTUAL_KEY
        self.deepseek_key = (
            deepseek_key
            if deepseek_key is not None
            else (settings.OPENAI_API_KEY or settings.DEEPSEEK_API_KEY)
        )
        self.timeout = float(timeout if timeout is not None else settings.WEB_SEARCH_TIMEOUT)
        self.max_attempts = max(
            1, int(max_attempts if max_attempts is not None else settings.WEB_SEARCH_MAX_ATTEMPTS)
        )
        self.retry_backoff = retry_backoff
        self._proxy_client = proxy_client
        self._direct_client = direct_client

    @property
    def _use_proxy(self) -> bool:
        return bool(self.virtual_key and self.proxy_url)

    @property
    def _use_direct(self) -> bool:
        return bool(self.deepseek_key or self._direct_client is not None)

    def _get_proxy_client(self) -> httpx.AsyncClient:
        if self._proxy_client is None or self._proxy_client.is_closed:
            self._proxy_client = httpx.AsyncClient(
                base_url=self.proxy_url,
                headers={
                    "Authorization": f"Bearer {self.virtual_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout, connect=5.0),
            )
        return self._proxy_client

    def _get_direct_client(self) -> httpx.AsyncClient:
        if self._direct_client is None or self._direct_client.is_closed:
            self._direct_client = httpx.AsyncClient(
                base_url=DEEPSEEK_API_BASE,
                headers={
                    "Authorization": f"Bearer {self.deepseek_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout, connect=5.0),
            )
        return self._direct_client

    async def close(self) -> None:
        for client in (self._proxy_client, self._direct_client):
            if client is not None and not client.is_closed:
                await client.aclose()

    # ---------------- 对外接口 ----------------

    async def search_web(
        self,
        query: str,
        *,
        count: Optional[int] = None,
        ori_question: Optional[str] = None,
        need_content: Optional[bool] = None,
        localization: Optional[str] = None,
        site: Optional[str] = None,
        top_n: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """联网搜索，返回规范化结果列表（默认截断到 ``WEB_SEARCH_TOP_N`` 条）。"""
        payload: dict[str, Any] = {
            "query": _build_query(query, site),
            "count": _clamp_count(count),
            "need_content": (
                settings.WEB_SEARCH_NEED_CONTENT if need_content is None else bool(need_content)
            ),
        }
        if ori_question:
            payload["ori_question"] = _truncate(str(ori_question).strip(), ORI_QUESTION_MAX_LEN)
        if localization:
            payload["localization"] = str(localization)

        data = await self._request(SEARCH_PATH, payload, op="search")
        results = [
            normalize_search_result(item)
            for item in (data.get("results") or [])
            if isinstance(item, dict)
        ]
        limit = int(top_n if top_n is not None else settings.WEB_SEARCH_TOP_N)
        return results[: max(0, limit)]

    async def fetch_url(self, url: str) -> dict[str, Any]:
        """抓取指定 URL 正文（Markdown）。"""
        u = str(url or "").strip()
        if not u or len(u) > URL_MAX_LEN or not u.lower().startswith(("http://", "https://")):
            raise ValueError(f"非法的 url：{u[:80]!r}")
        data = await self._request(FETCH_PATH, {"url": u}, op="fetch")
        return {
            "url": u,
            "title": str(data.get("title") or ""),
            "content": str(data.get("content") or ""),
        }

    # ---------------- 内部：链路选择 + 重试 ----------------

    async def _request(self, path: str, payload: dict[str, Any], *, op: str) -> dict[str, Any]:
        """透传优先、失败回退直连；两条链路均失败抛 :class:`WebSearchError`。"""
        attempted: list[str] = []
        last_error: Optional[BaseException] = None

        for mode in (MODE_PROXY, MODE_DIRECT):
            if mode == MODE_PROXY and not self._use_proxy:
                continue
            if mode == MODE_DIRECT and not self._use_direct:
                continue
            client = self._get_proxy_client() if mode == MODE_PROXY else self._get_direct_client()
            attempted.append(mode)
            try:
                return await self._request_with(client, path, payload, mode=mode, op=op)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                # 明确客户端错误（参数/鉴权）：不重试、不回退，直接暴露
                if code not in RETRYABLE_STATUS:
                    WEB_SEARCH_CALLS.labels(op=op, mode=mode, status="error").inc()
                    raise WebSearchError(_error_message(e.response), status_code=code) from e
                last_error = e
            except Exception as e:  # 链路不可用（未启动/连接失败/重试耗尽）
                last_error = e
            logger.warning("[web_search] %s 链路(%s)失败，尝试下一条链路：%s", op, mode, last_error)

        if last_error is None:
            raise WebSearchError(f"{op} 失败：未配置可用链路（LiteLLM 透传 / DeepSeek 直连）")
        if isinstance(last_error, WebSearchError):
            raise last_error
        raise WebSearchError(
            f"{op} 失败（已尝试链路：{','.join(attempted) or '无'}）：{last_error}"
        ) from last_error

    async def _request_with(
        self,
        client: httpx.AsyncClient,
        path: str,
        payload: dict[str, Any],
        *,
        mode: str,
        op: str,
    ) -> dict[str, Any]:
        """单链路请求：可重试错误按 ``max_attempts`` 退避重试；耗尽抛 :class:`WebSearchError`。"""
        last_error: Optional[BaseException] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await client.post(path, json=payload)
                response.raise_for_status()
                result = response.json()
                WEB_SEARCH_CALLS.labels(op=op, mode=mode, status="success").inc()
                return result
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in RETRYABLE_STATUS:
                    raise  # 交由 _request 判定：非可重试 → 不回退
                last_error = e
                status_label = "retry"
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
                last_error = e
                status_label = "retry"
            WEB_SEARCH_CALLS.labels(op=op, mode=mode, status=status_label).inc()
            logger.warning(
                "[web_search] %s 链路(%s) 第 %d/%d 次失败：%s",
                op, mode, attempt, self.max_attempts, type(last_error).__name__,
            )
            if attempt < self.max_attempts:
                await asyncio.sleep(self.retry_backoff * attempt)
        raise WebSearchError(
            f"{op} 链路({mode})重试耗尽：{last_error}"
        ) from last_error


_web_search_client: Optional[WebSearchClient] = None


def get_web_search_client() -> WebSearchClient:
    global _web_search_client
    if _web_search_client is None:
        _web_search_client = WebSearchClient()
    return _web_search_client


async def close_web_search_client() -> None:
    global _web_search_client
    if _web_search_client is not None:
        await _web_search_client.close()
        _web_search_client = None
