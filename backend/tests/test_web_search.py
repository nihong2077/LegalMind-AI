"""P2-WebSearch Step1：DeepSeek 联网检索客户端测试（httpx.MockTransport，无外部依赖）。

覆盖：仅经 LiteLLM 透传 / 结果规范化 / 参数约束 / 可重试重试 / 非可重试不重试 / 未配置代理 fail-closed。
"""
import json
import sys

import httpx
import pytest

sys.path.insert(0, ".")

from app.core.web_search import (  # noqa: E402
    WebSearchClient,
    WebSearchError,
    normalize_search_result,
)

PROXY_URL = "http://litellm:4000"


def _make_client(
    *,
    handler,
    base_url,
):
    return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))


def _client(
    *,
    proxy_handler=None,
    virtual_key="sk-virtual",
    **kwargs,
) -> WebSearchClient:
    return WebSearchClient(
        proxy_url=PROXY_URL,
        virtual_key=virtual_key,
        max_attempts=kwargs.pop("max_attempts", 2),
        retry_backoff=0.0,
        proxy_client=(
            _make_client(handler=proxy_handler, base_url=PROXY_URL)
            if proxy_handler
            else None
        ),
        **kwargs,
    )


def _search_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "results": [
                {
                    "title": f"结果{i}",
                    "url": f"https://ex.com/{i}",
                    "snippet": f"摘要{i}",
                    "summary": f"概要{i}",
                    "site_name": "示例网",
                    "rerank_score": 2.0,
                    "authority": 3,
                    "date": "2026-01-01T00:00:00Z",
                }
                for i in range(6)
            ]
        },
    )


@pytest.mark.asyncio
async def test_search_uses_proxy_and_normalizes():
    seen: list[dict] = []

    def proxy_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/tools/search"
        seen.append(json.loads(request.content))
        return _search_ok(request)

    client = _client(proxy_handler=proxy_handler)
    results = await client.search_web(
        "劳动 加班费 计算", count=8, ori_question="加班费怎么算？", site="pkulaw.com",
        top_n=3,
    )
    assert len(results) == 3  # top_n 截断
    assert results[0]["title"] == "结果0"
    # need_content=false 时正文回退到 summary，再回退 snippet
    assert results[0]["content"] == "概要0"
    # 参数：query 注入 site: 限定并限长、count 透传
    assert seen[0]["query"].startswith("site:pkulaw.com ")
    assert seen[0]["count"] == 8
    assert seen[0]["ori_question"] == "加班费怎么算？"
    assert seen[0]["need_content"] is False


@pytest.mark.asyncio
async def test_content_falls_back_to_snippet():
    normalized = normalize_search_result({"title": "t", "url": "u", "snippet": "只有摘要"})
    assert normalized["content"] == "只有摘要"
    assert normalized["summary"] == ""


@pytest.mark.asyncio
async def test_count_clamped_to_range():
    seen: list[dict] = []

    def proxy_handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _search_ok(request)

    client = _client(proxy_handler=proxy_handler)
    await client.search_web("a", count=999)
    await client.search_web("b", count=0)
    assert seen[0]["count"] == 50
    assert seen[1]["count"] == 1


@pytest.mark.asyncio
async def test_empty_query_raises_value_error():
    client = _client(proxy_handler=_search_ok)
    with pytest.raises(ValueError):
        await client.search_web("   ")


@pytest.mark.asyncio
async def test_proxy_failure_raises_without_direct_fallback():
    """透传链路不可用时直接失败，绝不回退直连厂商 API。"""

    def proxy_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("litellm down")

    client = _client(proxy_handler=proxy_handler)
    with pytest.raises(WebSearchError):
        await client.search_web("劳动法")


@pytest.mark.asyncio
async def test_retryable_status_is_retried_then_succeeds():
    calls = {"n": 0}

    def proxy_handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return _search_ok(request)

    client = _client(proxy_handler=proxy_handler, max_attempts=2)
    results = await client.search_web("劳动法")
    assert len(results) == 5
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_non_retryable_error_exposed():
    """明确客户端错误（4xx）不重试，直接暴露状态码。"""

    def proxy_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad query"}})

    client = _client(proxy_handler=proxy_handler)
    with pytest.raises(WebSearchError) as exc:
        await client.search_web("劳动法")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_fetch_url_returns_title_and_content():
    seen: list[dict] = []

    def proxy_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/tools/fetch"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"title": "示例页", "content": "# 正文\n内容"})

    client = _client(proxy_handler=proxy_handler)
    out = await client.fetch_url("https://ex.com/a")
    assert out["title"] == "示例页"
    assert out["content"].startswith("# 正文")
    assert seen[0]["url"] == "https://ex.com/a"


@pytest.mark.asyncio
async def test_fetch_url_validates():
    client = _client(proxy_handler=_search_ok)
    with pytest.raises(ValueError):
        await client.fetch_url("ftp://ex.com/a")
    with pytest.raises(ValueError):
        await client.fetch_url("")


@pytest.mark.asyncio
async def test_no_proxy_configured_fails_closed():
    """未配置虚拟 key（无 LiteLLM 代理）时 fail-closed，不直连厂商 API。"""
    client = _client(virtual_key="")
    with pytest.raises(WebSearchError):
        await client.search_web("劳动法")
