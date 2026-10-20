"""DeepSeek 官方联网检索客户端（Search + Fetch，P2-WebSearch Step1）

对齐 DeepSeek 官方文档 <https://api-docs.deepseek.com/zh-cn/guides/search>：

- ``POST /v1/tools/search``：联网搜索，返回结构化结果
  （``title/url/snippet/summary/content/site_name/date/authority/rerank_score``）；
- ``POST /v1/tools/fetch``：抓取指定 URL 正文（Markdown，``title/content``）。

**路由策略（仅经 LiteLLM 透传）**：一律经 **LiteLLM 代理**
（``litellm/config.yaml`` 的 ``pass_through_endpoints``）以 **虚拟 key** 调用——
DeepSeek 真实 key 由代理侧注入（``os.environ/DEEPSEEK_API_KEY``），后端全程不接触真实 key，
遵守密钥隔离约束；**未配置代理时直接抛 :class:`WebSearchError`，绝不直连厂商 API**。

**失败语义**：可重试错误（408/429/5xx 与连接/超时）按 ``WEB_SEARCH_MAX_ATTEMPTS`` 退避重试；
重试耗尽抛 :class:`WebSearchError`。**明确客户端错误（4xx，除 408/429）不重试**，避免遮蔽
真实参数/鉴权问题。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from .config import settings
from .metrics import WEB_SEARCH_CALLS

logger = logging.getLogger(__name__)

# DeepSeek 官方 API 路径（search/fetch 与 chat 同域，仅经 LiteLLM 透传访问）
SEARCH_PATH = "/v1/tools/search"
FETCH_PATH = "/v1/tools/fetch"

# 文档口径：query 1-128 字符、ori_question ≤128、count 1-50、url ≤8192
QUERY_MAX_LEN = 128
ORI_QUESTION_MAX_LEN = 128
COUNT_MIN, COUNT_MAX = 1, 50
URL_MAX_LEN = 8192

# 可重试状态码（对齐文档：408/429/5xx 可重试）
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# 链路标记（指标 label：proxy=透传）
MODE_PROXY = "proxy"


class WebSearchError(RuntimeError):
    """联网检索最终失败（LiteLLM 透传不可用 / 重试耗尽）。"""

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
    """联网检索客户端（Search/Fetch）。测试可注入 ``proxy_client``。"""

    def __init__(
        self,
        *,
        proxy_url: Optional[str] = None,
        virtual_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_attempts: Optional[int] = None,
        retry_backoff: float = 0.5,
        proxy_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.proxy_url = (proxy_url or settings.LITELLM_PROXY_URL).rstrip("/")
        self.virtual_key = virtual_key or settings.LITELLM_VIRTUAL_KEY
        self.timeout = float(timeout if timeout is not None else settings.WEB_SEARCH_TIMEOUT)
        self.max_attempts = max(
            1, int(max_attempts if max_attempts is not None else settings.WEB_SEARCH_MAX_ATTEMPTS)
        )
        self.retry_backoff = retry_backoff
        self._proxy_client = proxy_client

    @property
    def _use_proxy(self) -> bool:
        return bool(self.virtual_key and self.proxy_url)

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

    async def close(self) -> None:
        if self._proxy_client is not None and not self._proxy_client.is_closed:
            await self._proxy_client.aclose()

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
        """仅经 LiteLLM 透传；未配置代理或透传失败抛 :class:`WebSearchError`。"""
        if not self._use_proxy:
            raise WebSearchError(
                f"{op} 失败：未配置 LiteLLM 代理（LITELLM_PROXY_URL / LITELLM_VIRTUAL_KEY）；"
                "按密钥隔离约束，后端不直连厂商 API"
            )

        client = self._get_proxy_client()
        try:
            return await self._request_with(client, path, payload, mode=MODE_PROXY, op=op)
        except httpx.HTTPStatusError as e:
            # 明确客户端错误（参数/鉴权）：不重试，直接暴露
            WEB_SEARCH_CALLS.labels(op=op, mode=MODE_PROXY, status="error").inc()
            raise WebSearchError(
                _error_message(e.response), status_code=e.response.status_code
            ) from e
        except WebSearchError:
            raise
        except Exception as e:  # 透传链路不可用（未启动/连接失败/重试耗尽）
            raise WebSearchError(f"{op} 失败（链路：LiteLLM 透传）：{e}") from e

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
