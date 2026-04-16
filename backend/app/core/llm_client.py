import logging
from typing import AsyncIterator, Optional

import httpx

from .config import settings
from .redis_client import get_redis

logger = logging.getLogger(__name__)

LITELLM_CACHE_PREFIX = "legalmind:llm_cache:"
CACHE_TTL = 3600


class LLMClient:
    def __init__(
        self,
        proxy_url: Optional[str] = None,
        virtual_key: Optional[str] = None,
    ):
        self.proxy_url = (proxy_url or settings.LITELLM_PROXY_URL).rstrip("/")
        self.virtual_key = virtual_key or settings.LITELLM_VIRTUAL_KEY
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.proxy_url,
                headers={
                    "Authorization": f"Bearer {self.virtual_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        cache_key: Optional[str] = None,
    ) -> dict:
        if cache_key:
            cached = await self._get_cache(cache_key)
            if cached:
                logger.info("LLM 缓存命中: %s", cache_key)
                return cached

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        client = self._get_client()
        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        result = response.json()

        if cache_key and result.get("choices"):
            await self._set_cache(cache_key, result)

        return result

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncIterator[dict]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        client = self._get_client()
        async with client.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                import json
                try:
                    chunk = json.loads(data)
                    yield chunk
                except json.JSONDecodeError:
                    continue

    async def health_check(self) -> dict:
        try:
            client = self._get_client()
            response = await client.get("/health/liveliness")
            if response.status_code == 200:
                return {"status": "healthy", "proxy_url": self.proxy_url}
            return {"status": "degraded", "status_code": response.status_code}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def list_models(self) -> list[dict]:
        client = self._get_client()
        response = await client.get("/v1/models")
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])

    async def _get_cache(self, key: str) -> Optional[dict]:
        try:
            r = get_redis()
            import json
            cached = await r.get(f"{LITELLM_CACHE_PREFIX}{key}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        return None

    async def _set_cache(self, key: str, value: dict) -> None:
        try:
            r = get_redis()
            import json
            await r.setex(
                f"{LITELLM_CACHE_PREFIX}{key}",
                CACHE_TTL,
                json.dumps(value, ensure_ascii=False),
            )
        except Exception:
            pass


llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global llm_client
    if llm_client is None:
        llm_client = LLMClient()
    return llm_client


async def close_llm_client():
    global llm_client
    if llm_client:
        await llm_client.close()
        llm_client = None
