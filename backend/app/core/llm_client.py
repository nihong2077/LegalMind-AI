import json
import logging
from typing import AsyncIterator, Optional

import httpx
from langchain_openai import ChatOpenAI

from .config import settings
from .redis_client import get_redis

logger = logging.getLogger(__name__)

LITELLM_CACHE_PREFIX = "legalmind:llm_cache:"
CACHE_TTL = 3600

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_MODELS = {
    "deepseek-v4-pro": "deepseek-chat",
    "deepseek-flash": "deepseek-chat",
}

# 前端选择"法律领域微调模型"时发送的模型标识
LOCAL_FT_MODEL = "legalmind-ft"


class LLMClient:
    def __init__(
        self,
        proxy_url: Optional[str] = None,
        virtual_key: Optional[str] = None,
    ):
        self.proxy_url = (proxy_url or settings.LITELLM_PROXY_URL).rstrip("/")
        self.virtual_key = virtual_key or settings.LITELLM_VIRTUAL_KEY
        self._client: Optional[httpx.AsyncClient] = None
        self._direct_client: Optional[httpx.AsyncClient] = None
        self._local_client: Optional[httpx.AsyncClient] = None

    @property
    def _use_proxy(self) -> bool:
        return bool(self.virtual_key and self.proxy_url)

    @staticmethod
    def _is_local_model(model: str) -> bool:
        """判断是否为本地微调模型（路由到 Ollama）"""
        return model == LOCAL_FT_MODEL

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

    def _get_direct_client(self) -> httpx.AsyncClient:
        """直连 DeepSeek API 的客户端（单例复用）"""
        if self._direct_client is None or self._direct_client.is_closed:
            deepseek_key = settings.OPENAI_API_KEY or settings.DEEPSEEK_API_KEY
            self._direct_client = httpx.AsyncClient(
                base_url=DEEPSEEK_API_BASE,
                headers={
                    "Authorization": f"Bearer {deepseek_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._direct_client

    def _get_local_client(self) -> httpx.AsyncClient:
        """本地微调模型客户端（Ollama OpenAI 兼容接口，单例复用）"""
        if self._local_client is None or self._local_client.is_closed:
            self._local_client = httpx.AsyncClient(
                base_url=settings.LOCAL_LLM_API_BASE,
                headers={
                    "Authorization": f"Bearer {settings.LOCAL_LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._local_client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        if self._direct_client and not self._direct_client.is_closed:
            await self._direct_client.aclose()
        if self._local_client and not self._local_client.is_closed:
            await self._local_client.aclose()

    def get_chat_model(
        self,
        model: str = "deepseek-v4-pro",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        streaming: bool = False,
    ) -> ChatOpenAI:
        # 本地微调模型：走 Ollama OpenAI 兼容接口
        if self._is_local_model(model):
            return ChatOpenAI(
                model=settings.LOCAL_LLM_MODEL,
                openai_api_base=settings.LOCAL_LLM_API_BASE,
                openai_api_key=settings.LOCAL_LLM_API_KEY,
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=streaming,
            )

        if self.virtual_key and self.proxy_url:
            return ChatOpenAI(
                model=model,
                openai_api_base=f"{self.proxy_url}/v1",
                openai_api_key=self.virtual_key,
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=streaming,
            )

        deepseek_key = settings.OPENAI_API_KEY or settings.DEEPSEEK_API_KEY
        api_model = DEEPSEEK_MODELS.get(model, model)
        return ChatOpenAI(
            model=api_model,
            openai_api_base=DEEPSEEK_API_BASE,
            openai_api_key=deepseek_key,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        )

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

        if self._is_local_model(model):
            # 本地微调模型：Ollama 使用 LOCAL_LLM_MODEL 作为实际模型名
            payload["model"] = settings.LOCAL_LLM_MODEL
            client = self._get_local_client()
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            result = response.json()
        elif self._use_proxy:
            client = self._get_client()
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            result = response.json()
        else:
            api_model = DEEPSEEK_MODELS.get(model, model)
            payload["model"] = api_model
            client = self._get_direct_client()
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

        if self._is_local_model(model):
            # 本地微调模型：Ollama OpenAI 兼容流式接口
            payload["model"] = settings.LOCAL_LLM_MODEL
            client = self._get_local_client()
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        yield chunk
                    except json.JSONDecodeError:
                        continue
        elif self._use_proxy:
            client = self._get_client()
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        yield chunk
                    except json.JSONDecodeError:
                        continue
        else:
            api_model = DEEPSEEK_MODELS.get(model, model)
            payload["model"] = api_model
            client = self._get_direct_client()
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        yield chunk
                    except json.JSONDecodeError:
                        continue

    async def health_check(self) -> dict:
        try:
            if self._use_proxy:
                client = self._get_client()
                response = await client.get("/health/liveliness")
                if response.status_code == 200:
                    return {"status": "healthy", "proxy_url": self.proxy_url}
                return {"status": "degraded", "status_code": response.status_code}
            else:
                # 直连模式：简单验证 API Key 是否配置
                deepseek_key = settings.OPENAI_API_KEY or settings.DEEPSEEK_API_KEY
                if deepseek_key:
                    return {"status": "healthy", "mode": "direct", "api_base": DEEPSEEK_API_BASE}
                return {"status": "unhealthy", "error": "未配置 DEEPSEEK_API_KEY"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def local_health_check(self) -> dict:
        """检查本地微调模型是否可用（兼容 Ollama / llama.cpp server）"""
        try:
            client = self._get_local_client()
            response = await client.get("/models")
            if response.status_code == 200:
                data = response.json()
                model_list = data.get("data", [])
                if not model_list:
                    return {"status": "degraded", "error": "本地服务已运行但未加载模型"}
                # llama.cpp server 用文件路径作为模型 ID，Ollama 用模型名
                # 只要至少有一个模型就算可用（本地 server 同时只服务一个模型）
                model_ids = [m.get("id", "") for m in model_list]
                return {
                    "status": "healthy",
                    "model": model_ids[0],
                    "api_base": settings.LOCAL_LLM_API_BASE,
                }
            return {"status": "unhealthy", "status_code": response.status_code}
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
