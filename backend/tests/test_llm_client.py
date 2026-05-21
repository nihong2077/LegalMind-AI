import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.llm_client import LLMClient, close_llm_client, get_llm_client


@pytest.fixture
def mock_httpx_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def mock_httpx_client():
    client = AsyncMock()
    client.is_closed = False
    client.aclose = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_llm_client_chat(mock_httpx_client, mock_httpx_response):
    mock_httpx_response.json.return_value = {
        "id": "chatcmpl-123",
        "choices": [{"message": {"role": "assistant", "content": "你好"}}],
    }
    mock_httpx_client.post = AsyncMock(return_value=mock_httpx_response)

    client = LLMClient(proxy_url="http://localhost:4000", virtual_key="sk-test")
    client._client = mock_httpx_client

    result = await client.chat(
        model="deepseek-flash",
        messages=[{"role": "user", "content": "你好"}],
    )

    assert result["id"] == "chatcmpl-123"
    assert result["choices"][0]["message"]["content"] == "你好"
    mock_httpx_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_llm_client_chat_with_cache(mock_httpx_client, mock_httpx_response):
    mock_httpx_response.json.return_value = {
        "id": "chatcmpl-456",
        "choices": [{"message": {"role": "assistant", "content": "合同审查结果"}}],
    }
    mock_httpx_client.post = AsyncMock(return_value=mock_httpx_response)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    client = LLMClient(proxy_url="http://localhost:4000", virtual_key="sk-test")
    client._client = mock_httpx_client

    with patch("app.core.llm_client.get_redis", return_value=mock_redis):
        result = await client.chat(
            model="deepseek-flash",
            messages=[{"role": "user", "content": "审查合同"}],
            cache_key="contract_review_001",
        )

    assert result["id"] == "chatcmpl-456"
    mock_redis.setex.assert_called_once()


@pytest.mark.asyncio
async def test_llm_client_cache_hit():
    mock_redis = AsyncMock()
    cached_data = json.dumps({
        "id": "chatcmpl-789",
        "choices": [{"message": {"role": "assistant", "content": "缓存结果"}}],
    })
    mock_redis.get = AsyncMock(return_value=cached_data)

    client = LLMClient(proxy_url="http://localhost:4000", virtual_key="sk-test")
    client._client = AsyncMock()

    with patch("app.core.llm_client.get_redis", return_value=mock_redis):
        result = await client.chat(
            model="deepseek-flash",
            messages=[{"role": "user", "content": "测试"}],
            cache_key="cache_hit_key",
        )

    assert result["id"] == "chatcmpl-789"
    client._client.post.assert_not_called()


@pytest.mark.asyncio
async def test_llm_client_health_check_healthy(mock_httpx_client, mock_httpx_response):
    mock_httpx_client.get = AsyncMock(return_value=mock_httpx_response)

    client = LLMClient(proxy_url="http://localhost:4000", virtual_key="sk-test")
    client._client = mock_httpx_client

    result = await client.health_check()

    assert result["status"] == "healthy"
    assert result["proxy_url"] == "http://localhost:4000"


@pytest.mark.asyncio
async def test_llm_client_health_check_unhealthy():
    client = LLMClient(proxy_url="http://unreachable:4000", virtual_key="sk-test")
    client._client = AsyncMock()
    client._client.get = AsyncMock(side_effect=Exception("Connection refused"))

    result = await client.health_check()

    assert result["status"] == "unhealthy"
    assert "error" in result


@pytest.mark.asyncio
async def test_llm_client_list_models(mock_httpx_client, mock_httpx_response):
    mock_httpx_response.json.return_value = {
        "data": [
            {"id": "deepseek-v4-pro", "object": "model"},
            {"id": "deepseek-flash", "object": "model"},
        ]
    }
    mock_httpx_client.get = AsyncMock(return_value=mock_httpx_response)

    client = LLMClient(proxy_url="http://localhost:4000", virtual_key="sk-test")
    client._client = mock_httpx_client

    models = await client.list_models()

    assert len(models) == 2
    assert models[0]["id"] == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_get_llm_client_singleton():
    from app.core import llm_client as module

    module.llm_client = None
    client1 = get_llm_client()
    client2 = get_llm_client()
    assert client1 is client2
    module.llm_client = None


@pytest.mark.asyncio
async def test_close_llm_client():
    from app.core import llm_client as module

    mock_client = AsyncMock()
    mock_client.close = AsyncMock()
    module.llm_client = mock_client

    await close_llm_client()

    mock_client.close.assert_called_once()
    assert module.llm_client is None
