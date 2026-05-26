import asyncio
import functools
import json
import logging
import os
import time
import uuid
from enum import Enum
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..core.config import settings
from ..core.llm_client import get_llm_client
from ..core.redis_client import (
    enqueue_task,
    generate_task_id,
    get_redis,
    get_stream_events,
    get_task_status,
)
from ..core.security import create_access_token, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["gateway"])

CIRCUIT_BREAKER_PREFIX = "legalmind:cb:"
SSE_PING_INTERVAL = 15


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def is_allowed(self, key: str) -> bool:
        r = get_redis()
        now = time.time()
        window_start = now - self.window_seconds
        pipe = r.pipeline()
        pipe.zremrangebyscore(f"ratelimit:{key}", 0, window_start)
        pipe.zcard(f"ratelimit:{key}")
        pipe.zadd(f"ratelimit:{key}", {str(now): now})
        pipe.expire(f"ratelimit:{key}", self.window_seconds + 1)
        results = await pipe.execute()
        current_count = results[1]
        if current_count >= self.max_requests:
            return False
        return True


rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.RATE_LIMIT_MAX_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class RedisCircuitBreaker:
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

    def _key(self) -> str:
        return f"{CIRCUIT_BREAKER_PREFIX}{self.name}"

    async def _get_state(self) -> dict:
        r = get_redis()
        data = await r.hgetall(self._key())
        if not data:
            return {
                "state": CircuitState.CLOSED.value,
                "failure_count": "0",
                "last_failure_time": "",
                "half_open_success": "0",
            }
        return data

    async def _set_state(self, updates: dict) -> None:
        r = get_redis()
        await r.hset(self._key(), mapping=updates)
        await r.expire(self._key(), self.recovery_timeout * 3)

    async def get_current_state(self) -> CircuitState:
        data = await self._get_state()
        current = CircuitState(data.get("state", CircuitState.CLOSED.value))
        if current == CircuitState.OPEN:
            last_failure = float(data.get("last_failure_time") or "0")
            if time.time() - last_failure >= self.recovery_timeout:
                await self._set_state({
                    "state": CircuitState.HALF_OPEN.value,
                    "half_open_success": "0",
                })
                return CircuitState.HALF_OPEN
        return current

    async def record_success(self) -> None:
        data = await self._get_state()
        current = CircuitState(data.get("state", CircuitState.CLOSED.value))
        if current == CircuitState.HALF_OPEN:
            half_open = int(data.get("half_open_success", "0")) + 1
            if half_open >= self.half_open_max:
                await self._set_state({
                    "state": CircuitState.CLOSED.value,
                    "failure_count": "0",
                    "half_open_success": "0",
                })
            else:
                await self._set_state({"half_open_success": str(half_open)})
        else:
            await self._set_state({"failure_count": "0"})

    async def record_failure(self) -> None:
        data = await self._get_state()
        failure_count = int(data.get("failure_count", "0")) + 1
        updates = {
            "failure_count": str(failure_count),
            "last_failure_time": str(time.time()),
        }
        if failure_count >= self.failure_threshold:
            updates["state"] = CircuitState.OPEN.value
        await self._set_state(updates)

    async def is_available(self) -> bool:
        state = await self.get_current_state()
        return state != CircuitState.OPEN

    async def reset(self) -> None:
        await self._set_state({
            "state": CircuitState.CLOSED.value,
            "failure_count": "0",
            "last_failure_time": "",
            "half_open_success": "0",
        })


def circuit_protect(name: str = "default", fallback: Optional[Callable] = None):
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            cb = RedisCircuitBreaker(
                name=name,
                failure_threshold=settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                recovery_timeout=settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
                half_open_max=settings.CIRCUIT_BREAKER_HALF_OPEN_MAX,
            )
            if not await cb.is_available():
                if fallback:
                    return await fallback(*args, **kwargs)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"服务 [{name}] 暂时不可用，熔断保护中",
                )
            try:
                result = await func(*args, **kwargs)
                await cb.record_success()
                return result
            except Exception as e:
                await cb.record_failure()
                if fallback:
                    return await fallback(*args, **kwargs)
                raise

        return wrapper

    return decorator


def _build_rate_limit_key(request: Request, user: dict) -> str:
    client_ip = request.client.host if request.client else "unknown"
    user_id = user.get("sub", "anonymous")
    route = request.url.path
    return f"{client_ip}:{user_id}:{route}"


async def check_rate_limit(request: Request, user: dict = Depends(get_current_user)):
    key = _build_rate_limit_key(request, user)
    allowed = await rate_limiter.is_allowed(key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        )
    return user


@router.post("/auth/token")
async def login(username: str = Query(...), password: str = Query(...)):
    if username != "admin" or password != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_access_token(data={"sub": username})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/tasks")
async def create_task(
    task_type: str,
    payload: dict,
    user: dict = Depends(check_rate_limit),
):
    task_id = generate_task_id()
    result_id = await enqueue_task(task_type=task_type, payload=payload, task_id=task_id)
    return {"task_id": result_id, "status": "pending"}


@router.get("/tasks/{task_id}")
async def query_task_status(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    status_data = await get_task_status(task_id)
    if not status_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    return status_data


@router.get("/stream/{task_id}")
async def stream_task_progress(
    task_id: str,
    request: Request,
    last_event_id: Optional[str] = Query(None, alias="Last-Event-ID"),
    user: dict = Depends(get_current_user),
):
    status_data = await get_task_status(task_id)
    if not status_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )

    start_id = last_event_id or "0"

    async def event_generator():
        current_id = start_id
        last_ping = time.time()

        while True:
            if await request.is_disconnected():
                break

            events = await get_stream_events(task_id, last_id=current_id, count=10, block=3000)

            if events:
                for msg_id, msg in events:
                    current_id = msg_id
                    data = msg.get("data", "{}")
                    yield {
                        "id": msg_id,
                        "event": "message",
                        "data": data,
                    }

                    try:
                        parsed = json.loads(data)
                        if parsed.get("status") in ("completed", "failed"):
                            return
                    except json.JSONDecodeError:
                        pass
                last_ping = time.time()
            else:
                current_status = await get_task_status(task_id)
                if current_status and current_status.get("status") in ("completed", "failed"):
                    final_data = json.dumps({
                        "status": current_status["status"],
                        "progress": current_status.get("progress", "100"),
                        "result": current_status.get("result", ""),
                        "error": current_status.get("error", ""),
                    }, ensure_ascii=False)
                    yield {
                        "id": "final",
                        "event": "message",
                        "data": final_data,
                    }
                    return

            now = time.time()
            if now - last_ping >= SSE_PING_INTERVAL:
                yield {
                    "event": "ping",
                    "data": "",
                }
                last_ping = now

            await asyncio.sleep(0.1)

    return EventSourceResponse(
        event_generator(),
        ping=SSE_PING_INTERVAL,
        sep="\n",
    )


@router.get("/circuit-breaker/{name}")
async def get_circuit_status(name: str, user: dict = Depends(get_current_user)):
    cb = RedisCircuitBreaker(name=name)
    data = await cb._get_state()
    return {
        "name": name,
        "state": data.get("state", CircuitState.CLOSED.value),
        "failure_count": data.get("failure_count", "0"),
        "last_failure_time": data.get("last_failure_time", ""),
        "half_open_success": data.get("half_open_success", "0"),
    }


@router.post("/circuit-breaker/{name}/reset")
async def reset_circuit(name: str, user: dict = Depends(get_current_user)):
    cb = RedisCircuitBreaker(name=name)
    await cb.reset()
    return {"name": name, "state": CircuitState.CLOSED.value, "message": "熔断器已重置"}


LEGAL_SYSTEM_PROMPT = """你是 LegalMind AI，一个专业的中国法律智能助手。你的职责是：

1. 基于中国法律法规（民法典、刑法、劳动法、合同法等）提供专业法律分析
2. 用清晰易懂的语言解释法律概念和条文
3. 提供实用的法律建议和操作指引
4. 在涉及具体案件时提醒用户咨询专业律师

回答要求：
- 引用具体法律条文时标注法律名称和条号
- 区分法律意见和事实陈述
- 涉及诉讼时效、管辖等关键信息时重点提示
- 不得提供虚假或误导性法律信息
- 如不确定，明确告知并建议咨询专业律师"""


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str = "gemma4-9b"
    temperature: float = 0.7
    max_tokens: int = 2048


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: dict = Depends(check_rate_limit),
):
    cb = RedisCircuitBreaker(name="llm_service")
    if not await cb.is_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM 服务暂时不可用，熔断保护中",
        )

    messages = body.messages
    if not any(m.get("role") == "system" for m in messages):
        messages = [{"role": "system", "content": LEGAL_SYSTEM_PROMPT}] + messages

    llm = get_llm_client()

    async def event_generator():
        full_content = ""
        try:
            async for chunk in llm.chat_stream(
                model=body.model,
                messages=messages,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            ):
                if await request.is_disconnected():
                    break

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_content += content
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "content": content,
                            "role": "assistant",
                        }, ensure_ascii=False),
                    }

            yield {
                "event": "done",
                "data": json.dumps({
                    "content": full_content,
                    "role": "assistant",
                    "finish_reason": "stop",
                }, ensure_ascii=False),
            }

            await cb.record_success()

            r = get_redis()
            await r.incr(f"{DASHBOARD_STATS_PREFIX}chat_count")

        except Exception as e:
            logger.error("LLM 流式调用失败: %s", e)
            await cb.record_failure()
            yield {
                "event": "error",
                "data": json.dumps({
                    "error": str(e),
                    "message": "AI 服务暂时不可用，请稍后重试",
                }, ensure_ascii=False),
            }

    return EventSourceResponse(
        event_generator(),
        ping=SSE_PING_INTERVAL,
        sep="\n",
    )


@router.post("/chat")
async def chat_completion(
    body: ChatRequest,
    user: dict = Depends(check_rate_limit),
):
    cb = RedisCircuitBreaker(name="llm_service")
    if not await cb.is_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM 服务暂时不可用，熔断保护中",
        )

    messages = body.messages
    if not any(m.get("role") == "system" for m in messages):
        messages = [{"role": "system", "content": LEGAL_SYSTEM_PROMPT}] + messages

    llm = get_llm_client()
    try:
        result = await llm.chat(
            model=body.model,
            messages=messages,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        await cb.record_success()
        return result
    except Exception as e:
        await cb.record_failure()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM 服务调用失败: {str(e)}",
        )


DASHBOARD_STATS_PREFIX = "legalmind:stats:"
DOCUMENTS_PREFIX = "legalmind:docs:"
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")


@router.get("/dashboard/stats")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    r = get_redis()
    chat_count = int(await r.get(f"{DASHBOARD_STATS_PREFIX}chat_count") or 0)
    doc_count = int(await r.get(f"{DASHBOARD_STATS_PREFIX}doc_count") or 0)
    knowledge_count = int(await r.get(f"{DASHBOARD_STATS_PREFIX}knowledge_count") or 2450)

    return {
        "chat_count": chat_count,
        "doc_count": doc_count,
        "knowledge_count": knowledge_count,
        "efficiency_gain": "+45%",
    }


@router.post("/dashboard/stats/increment")
async def increment_stat(
    key: str = Query(..., description="要增加的统计键: chat_count / doc_count"),
    user: dict = Depends(get_current_user),
):
    if key not in ("chat_count", "doc_count"):
        raise HTTPException(status_code=400, detail="不支持的统计键")
    r = get_redis()
    await r.incr(f"{DASHBOARD_STATS_PREFIX}{key}")
    return {"status": "ok", "key": key}


@router.get("/dashboard/cases")
async def get_recent_cases(user: dict = Depends(get_current_user)):
    r = get_redis()
    cases_raw = await r.lrange(f"{DASHBOARD_STATS_PREFIX}cases", 0, 9)
    cases = []
    for c in cases_raw:
        try:
            cases.append(json.loads(c))
        except json.JSONDecodeError:
            continue
    return cases


@router.post("/dashboard/cases")
async def create_case(
    title: str,
    description: str = "",
    user: dict = Depends(get_current_user),
):
    r = get_redis()
    case = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "description": description,
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    await r.lpush(f"{DASHBOARD_STATS_PREFIX}cases", json.dumps(case, ensure_ascii=False))
    await r.ltrim(f"{DASHBOARD_STATS_PREFIX}cases", 0, 49)
    return case


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: dict = Depends(check_rate_limit),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    allowed_ext = {".pdf", ".docx", ".txt", ".doc"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    doc_id = str(uuid.uuid4())[:8]
    save_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{file.filename}")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小不能超过 10MB")

    with open(save_path, "wb") as f:
        f.write(content)

    r = get_redis()
    doc_info = {
        "id": doc_id,
        "name": file.filename,
        "size": f"{len(content) / 1024:.1f} KB",
        "type": ext[1:].upper(),
        "status": "uploaded",
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M"),
        "path": save_path,
    }
    await r.hset(f"{DOCUMENTS_PREFIX}{doc_id}", mapping=doc_info)
    await r.incr(f"{DASHBOARD_STATS_PREFIX}doc_count")

    return doc_info


@router.get("/documents")
async def list_documents(user: dict = Depends(get_current_user)):
    r = get_redis()
    keys = []
    async for key in r.scan_iter(f"{DOCUMENTS_PREFIX}*"):
        keys.append(key)

    docs = []
    for key in keys:
        data = await r.hgetall(key)
        if data:
            doc = {k: v for k, v in data.items() if k != "path"}
            docs.append(doc)
    docs.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return docs


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, user: dict = Depends(get_current_user)):
    r = get_redis()
    data = await r.hgetall(f"{DOCUMENTS_PREFIX}{doc_id}")
    if not data:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {k: v for k, v in data.items() if k != "path"}


@router.get("/documents/{doc_id}/content")
async def get_document_content(doc_id: str, user: dict = Depends(get_current_user)):
    r = get_redis()
    data = await r.hgetall(f"{DOCUMENTS_PREFIX}{doc_id}")
    if not data:
        raise HTTPException(status_code=404, detail="文档不存在")

    file_path = data.get("path", "")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = os.path.splitext(file_path)[1].lower()
    text_content = ""

    try:
        if ext == ".txt":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text_content = f.read()
        elif ext == ".pdf":
            try:
                import fitz
                doc = fitz.open(file_path)
                for page in doc:
                    text_content += page.get_text()
                doc.close()
            except ImportError:
                text_content = f"[PDF文件: {data.get('name', '')}]"
        elif ext in (".docx", ".doc"):
            try:
                from docx import Document
                doc = Document(file_path)
                text_content = "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                text_content = f"[Word文件: {data.get('name', '')}]"
        else:
            text_content = f"[文件: {data.get('name', '')}]"
    except Exception as e:
        logger.warning("读取文档内容失败: %s", e)
        text_content = f"[读取失败: {data.get('name', '')}]"

    return {"doc_id": doc_id, "name": data.get("name", ""), "content": text_content[:50000]}


@router.post("/documents/{doc_id}/analyze")
async def analyze_document(
    doc_id: str,
    user: dict = Depends(check_rate_limit),
):
    r = get_redis()
    data = await r.hgetall(f"{DOCUMENTS_PREFIX}{doc_id}")
    if not data:
        raise HTTPException(status_code=404, detail="文档不存在")

    await r.hset(f"{DOCUMENTS_PREFIX}{doc_id}", "status", "analyzing")

    task_id = generate_task_id()
    await enqueue_task(
        task_type="document_analysis",
        payload={"doc_id": doc_id, "doc_name": data.get("name", "")},
        task_id=task_id,
    )

    return {"task_id": task_id, "doc_id": doc_id, "status": "analyzing"}


class AgentRequest(BaseModel):
    query: str
    context: str = ""
    task_type: str = "analyze"


@router.post("/agents/run")
async def run_agent(
    body: AgentRequest,
    user: dict = Depends(check_rate_limit),
):
    from ..services.workflows import build_legal_workflow
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    heavy_llm = llm_client.get_chat_model(model="deepseek-v4-pro", temperature=0.7, max_tokens=4096)
    fast_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.5, max_tokens=2048)

    workflow = build_legal_workflow(heavy_llm=heavy_llm, fast_llm=fast_llm)

    result = await workflow.ainvoke({
        "messages": [],
        "query": body.query,
        "context": body.context,
        "task_type": body.task_type,
        "analysis_result": "",
        "review_result": "",
        "research_result": "",
        "final_result": "",
    })

    return {"result": result.get("final_result", ""), "task_type": body.task_type}


@router.post("/agents/stream")
async def stream_agent(
    body: AgentRequest,
    request: Request,
    user: dict = Depends(check_rate_limit),
):
    from ..services.agents import LegalAnalyzer, ContractReviewer, RegulatoryResearcher
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    heavy_llm = llm_client.get_chat_model(model="deepseek-v4-pro", temperature=0.7, max_tokens=4096, streaming=True)
    fast_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.5, max_tokens=2048, streaming=True)

    async def event_generator():
        try:
            if body.task_type in ("analyze", "full"):
                analyzer = LegalAnalyzer(heavy_llm)
                async for chunk in analyzer.analyze_stream(body.query, body.context):
                    yield {"event": "analysis", "data": json.dumps({"content": chunk}, ensure_ascii=False)}

            if body.task_type in ("review", "full"):
                reviewer = ContractReviewer(heavy_llm)
                async for chunk in reviewer.review_stream(body.context or body.query):
                    yield {"event": "review", "data": json.dumps({"content": chunk}, ensure_ascii=False)}

            if body.task_type in ("research", "full"):
                researcher = RegulatoryResearcher(fast_llm)
                async for chunk in researcher.research_stream(body.query):
                    yield {"event": "research", "data": json.dumps({"content": chunk}, ensure_ascii=False)}

            yield {"event": "done", "data": json.dumps({"status": "completed"}, ensure_ascii=False)}
        except Exception as e:
            logger.error(f"Agent stream error: {e}")
            yield {"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator(), ping=SSE_PING_INTERVAL, sep="\n")


class KnowledgeSearchRequest(BaseModel):
    query: str
    domain: str = "law"
    top_k: int = 8
    use_hyde: bool = True


class KnowledgeListRequest(BaseModel):
    domain: str = "law"
    category: str = ""
    keyword: str = ""
    page: int = 1
    page_size: int = 20


@router.post("/knowledge/search")
async def search_knowledge(
    body: KnowledgeSearchRequest,
    user: dict = Depends(check_rate_limit),
):
    from ..services.legal.rag_retriever import retrieve_legal_knowledge
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    fast_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.3, max_tokens=1024)

    results = await retrieve_legal_knowledge(
        query=body.query,
        llm=fast_llm,
        top_k=body.top_k,
        use_hyde=body.use_hyde,
        domain=body.domain,
    )

    return {"results": results, "total": len(results)}


@router.get("/knowledge/list")
async def list_knowledge(
    domain: str = Query("law"),
    category: str = Query(""),
    keyword: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    from ..core.pg_client import ENGINES
    from sqlalchemy.ext.asyncio import AsyncSession

    if domain not in ("law", "judge", "lawyer"):
        raise HTTPException(status_code=400, detail="domain 必须为 law/judge/lawyer")

    engine = ENGINES.get(domain)
    if not engine:
        raise HTTPException(status_code=400, detail=f"未知的领域: {domain}")

    offset = (page - 1) * page_size
    items = []
    total = 0

    try:
        from sqlalchemy import text
        async with AsyncSession(engine) as session:
            if domain == "law":
                table = "legal_provisions"
                where_parts = []
                params = {}
                if keyword:
                    where_parts.append("content ILIKE :kw OR law_name ILIKE :kw")
                    params["kw"] = f"%{keyword}%"
                if category:
                    where_parts.append("law_type = :cat")
                    params["cat"] = category
                where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

                count_sql = f"SELECT COUNT(*) FROM {table}{where_clause}"
                data_sql = f"SELECT law_name, law_type, chapter, section, article_number, article_title, content, effective_date, status FROM {table}{where_clause} ORDER BY law_name, article_number LIMIT :limit OFFSET :offset"
                params["limit"] = page_size
                params["offset"] = offset

                count_result = await session.execute(text(count_sql), params)
                total = count_result.scalar() or 0

                data_result = await session.execute(text(data_sql), params)
                rows = data_result.fetchall()
                for row in rows:
                    items.append({
                        "law_name": row[0],
                        "law_type": row[1],
                        "chapter": row[2],
                        "section": row[3],
                        "article_number": row[4],
                        "article_title": row[5],
                        "content": row[6],
                        "effective_date": str(row[7]) if row[7] else "",
                        "status": row[8],
                    })
            elif domain == "judge":
                table = "judge_cases"
                where_parts = []
                params = {}
                if keyword:
                    where_parts.append("case_name ILIKE :kw OR cause_of_action ILIKE :kw")
                    params["kw"] = f"%{keyword}%"
                if category:
                    where_parts.append("case_type = :cat")
                    params["cat"] = category
                where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

                count_sql = f"SELECT COUNT(*) FROM {table}{where_clause}"
                data_sql = f"SELECT case_number, case_name, court_name, case_type, cause_of_action, judgment_date, judgment_result FROM {table}{where_clause} ORDER BY judgment_date DESC LIMIT :limit OFFSET :offset"
                params["limit"] = page_size
                params["offset"] = offset

                count_result = await session.execute(text(count_sql), params)
                total = count_result.scalar() or 0

                data_result = await session.execute(text(data_sql), params)
                rows = data_result.fetchall()
                for row in rows:
                    items.append({
                        "case_number": row[0],
                        "case_name": row[1],
                        "court_name": row[2],
                        "case_type": row[3],
                        "cause_of_action": row[4],
                        "judgment_date": str(row[5]) if row[5] else "",
                        "judgment_result": row[6],
                    })
            elif domain == "lawyer":
                table = "defense_strategies"
                where_parts = []
                params = {}
                if keyword:
                    where_parts.append("strategy_name ILIKE :kw OR argument_template ILIKE :kw")
                    params["kw"] = f"%{keyword}%"
                if category:
                    where_parts.append("case_type = :cat")
                    params["cat"] = category
                where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

                count_sql = f"SELECT COUNT(*) FROM {table}{where_clause}"
                data_sql = f"SELECT strategy_name, case_type, applicable_scenario, argument_template, success_rate FROM {table}{where_clause} ORDER BY strategy_name LIMIT :limit OFFSET :offset"
                params["limit"] = page_size
                params["offset"] = offset

                count_result = await session.execute(text(count_sql), params)
                total = count_result.scalar() or 0

                data_result = await session.execute(text(data_sql), params)
                rows = data_result.fetchall()
                for row in rows:
                    items.append({
                        "strategy_name": row[0],
                        "case_type": row[1],
                        "applicable_scenario": row[2],
                        "argument_template": row[3],
                        "success_rate": row[4],
                    })
    except Exception as e:
        logger.warning("知识库列表查询失败: %s", e)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


class DebateRequest(BaseModel):
    case_description: str
    evidence_summary: str = ""
    task_type: str = "debate"


@router.post("/debate/run")
async def run_debate(
    body: DebateRequest,
    user: dict = Depends(check_rate_limit),
):
    from ..services.workflows import build_debate_workflow
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    heavy_llm = llm_client.get_chat_model(model="deepseek-v4-pro", temperature=0.7, max_tokens=4096)
    fast_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.5, max_tokens=2048)

    workflow = build_debate_workflow(heavy_llm=heavy_llm, fast_llm=fast_llm)

    result = await workflow.ainvoke({
        "messages": [],
        "case_description": body.case_description,
        "evidence_summary": body.evidence_summary,
        "task_type": body.task_type,
        "kfe": {},
        "evidence_sufficient": True,
        "interrupt_reason": "",
        "focus_points": "",
        "plaintiff_opening": "",
        "defendant_opening": "",
        "court_investigation": "",
        "current_round": 0,
        "plaintiff_args": [],
        "defendant_args": [],
        "judge_comments": [],
        "converged": False,
        "convergence_reason": "",
        "verdict": "",
        "judgment_report": "",
        "plain_language_version": "",
        "legal_knowledge": "",
        "final_result": "",
        "structured_summary": {},
    })

    return {
        "result": result.get("final_result", ""),
        "verdict": result.get("verdict", ""),
        "judgment_report": result.get("judgment_report", ""),
        "plain_language": result.get("plain_language_version", ""),
        "convergence_reason": result.get("convergence_reason", ""),
        "kfe": result.get("kfe", {}),
        "evidence_sufficient": result.get("evidence_sufficient", True),
        "interrupt_reason": result.get("interrupt_reason", ""),
    }


@router.post("/debate/stream")
async def stream_debate(
    body: DebateRequest,
    request: Request,
    user: dict = Depends(check_rate_limit),
):
    from ..services.workflows import build_debate_workflow
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    heavy_llm = llm_client.get_chat_model(model="deepseek-v4-pro", temperature=0.7, max_tokens=4096, streaming=True)
    fast_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.5, max_tokens=2048, streaming=True)

    workflow = build_debate_workflow(heavy_llm=heavy_llm, fast_llm=fast_llm)

    async def event_generator():
        try:
            input_state = {
                "messages": [],
                "case_description": body.case_description,
                "evidence_summary": body.evidence_summary,
                "task_type": body.task_type,
                "kfe": {},
                "evidence_sufficient": True,
                "interrupt_reason": "",
                "focus_points": "",
                "plaintiff_opening": "",
                "defendant_opening": "",
                "court_investigation": "",
                "current_round": 0,
                "plaintiff_args": [],
                "defendant_args": [],
                "judge_comments": [],
                "converged": False,
                "convergence_reason": "",
                "verdict": "",
                "judgment_report": "",
                "plain_language_version": "",
                "legal_knowledge": "",
                "final_result": "",
                "structured_summary": {},
            }

            # 辩论发言节点：这些节点的输出需要流式展示给前端
            SPEECH_NODES = {
                "judge_opening", "plaintiff_opening", "defendant_opening",
                "court_investigation", "plaintiff_rebuttal", "defendant_rebuttal",
                "judge_comment", "judge_verdict", "judgment_report", "plain_language",
            }

            # 使用 astream（节点级输出）替代 astream_events（token 级事件）
            # stream_mode="updates" 返回 {node_name: output} 字典
            async for chunk in workflow.astream(input_state, stream_mode="updates"):
                if await request.is_disconnected():
                    break

                if not isinstance(chunk, dict) or len(chunk) != 1:
                    continue

                node_name, output = next(iter(chunk.items()))

                # KFE 提取完成 → 发送 metadata
                if node_name == "extract_kfe" and output.get("kfe"):
                    yield {
                        "event": "metadata",
                        "data": json.dumps({
                            "type": "extract_kfe",
                            "node": node_name,
                            "kfe": output.get("kfe"),
                        }, ensure_ascii=False, default=str),
                    }

                # 法律检索完成 → 发送 metadata
                elif node_name == "retrieve_knowledge" and output.get("legal_knowledge"):
                    yield {
                        "event": "metadata",
                        "data": json.dumps({
                            "type": "retrieve_knowledge",
                            "node": node_name,
                            "legal_knowledge": output.get("legal_knowledge"),
                        }, ensure_ascii=False, default=str),
                    }

                # 辩论发言节点 → 逐字符模拟流式输出消息
                elif node_name in SPEECH_NODES:
                    # 从 messages 或对应字段提取发言内容
                    content = ""
                    field_map = {
                        "judge_opening": "focus_points",
                        "plaintiff_opening": "plaintiff_opening",
                        "defendant_opening": "defendant_opening",
                        "court_investigation": "court_investigation",
                        "plaintiff_rebuttal": None,
                        "defendant_rebuttal": None,
                        "judge_comment": None,
                        "judge_verdict": "verdict",
                        "judgment_report": "judgment_report",
                        "plain_language": "plain_language_version",
                    }
                    field = field_map.get(node_name)
                    if field and output.get(field):
                        content = output[field]
                    else:
                        msgs = output.get("messages", [])
                        if msgs:
                            content = msgs[-1].content if hasattr(msgs[-1], 'content') else str(msgs[-1])

                    if content:
                        # 模拟流式：按句子分块发送
                        import re
                        sentences = re.split(r'(?<=[。！？\n])', content)
                        for sentence in sentences:
                            if sentence.strip():
                                yield {
                                    "event": "message",
                                    "data": json.dumps({
                                        "node": node_name,
                                        "content": sentence,
                                    }, ensure_ascii=False),
                                }

                # 最终汇总节点 → 发送 done 事件
                elif node_name == "finalize":
                    structured = output.get("structured_summary") or {}
                    # 确保 structured_summary 中包含 kfe 和法律知识
                    if not structured.get("kfe_items") and output.get("kfe"):
                        kfe_raw = output.get("kfe", {})
                        kfe_list = []
                        for k, v in kfe_raw.items():
                            if isinstance(v, dict):
                                for sk, sv in v.items():
                                    kfe_list.append({"label": f"{k}-{sk}", "value": str(sv), "status": "verified"})
                            else:
                                kfe_list.append({"label": k, "value": str(v), "status": "verified"})
                        structured["kfe_items"] = kfe_list
                    yield {
                        "event": "done",
                        "data": json.dumps({
                            "status": "completed",
                            "final_result": output.get("final_result", ""),
                            "verdict": output.get("verdict", ""),
                            "judgment_report": output.get("judgment_report", ""),
                            "plain_language": output.get("plain_language_version", ""),
                            "convergence_reason": output.get("convergence_reason", ""),
                            "kfe": output.get("kfe", {}),
                            "legal_knowledge": output.get("legal_knowledge", ""),
                            "evidence_sufficient": output.get("evidence_sufficient", True),
                            "interrupt_reason": output.get("interrupt_reason", ""),
                            "structured_summary": structured,
                        }, ensure_ascii=False, default=str),
                    }

        except Exception as e:
            logger.exception("Debate stream error")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator(), ping=SSE_PING_INTERVAL, sep="\n")


@router.post("/debate/kfe")
async def extract_kfe_only(
    body: DebateRequest,
    user: dict = Depends(check_rate_limit),
):
    from ..services.legal import extract_kfe
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.3, max_tokens=1024)

    kfe = await extract_kfe(
        case_description=body.case_description,
        evidence_summary=body.evidence_summary,
        llm=llm,
    )

    from ..services.legal import check_evidence_sufficiency
    sufficient, reason = check_evidence_sufficiency(kfe)

    return {
        "kfe": kfe,
        "evidence_sufficient": sufficient,
        "interrupt_reason": reason if not sufficient else "",
    }


class ContractReviewRequest(BaseModel):
    contract_text: str
    user_position: str = "乙方"
    review_stance: str = "常规"


@router.post("/contract/review")
async def review_contract(
    body: ContractReviewRequest,
    user: dict = Depends(check_rate_limit),
):
    from ..services.workflows import build_contract_review_workflow
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    heavy_llm = llm_client.get_chat_model(model="deepseek-v4-pro", temperature=0.5, max_tokens=4096)
    fast_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.3, max_tokens=2048)

    workflow = build_contract_review_workflow(heavy_llm=heavy_llm, fast_llm=fast_llm)

    result = await workflow.ainvoke({
        "contract_text": body.contract_text,
        "user_position": body.user_position,
        "review_stance": body.review_stance,
        "classification": {},
        "risks": {},
        "report": "",
        "summary": {},
        "final_result": "",
        "structured_review": {},
    })

    return {
        "summary": result.get("summary", {}),
        "report": result.get("report", ""),
        "classification": result.get("classification", {}),
        "risks": result.get("risks", {}),
    }


@router.post("/contract/review/stream")
async def review_contract_stream(
    body: ContractReviewRequest,
    request: Request,
    user: dict = Depends(check_rate_limit),
):
    from ..services.workflows import build_contract_review_workflow
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    heavy_llm = llm_client.get_chat_model(model="deepseek-v4-pro", temperature=0.5, max_tokens=4096)
    fast_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.3, max_tokens=2048)

    workflow = build_contract_review_workflow(heavy_llm=heavy_llm, fast_llm=fast_llm)

    async def event_generator():
        try:
            input_state = {
                "contract_text": body.contract_text,
                "user_position": body.user_position,
                "review_stance": body.review_stance,
                "classification": {},
                "risks": {},
                "report": "",
                "summary": {},
                "final_result": "",
            }

            async for chunk in workflow.astream(input_state, stream_mode="updates"):
                if await request.is_disconnected():
                    break

                if not isinstance(chunk, dict) or len(chunk) != 1:
                    continue

                node_name, output = next(iter(chunk.items()))

                if not isinstance(output, dict):
                    continue

                # 条款分类完成
                if node_name == "classify":
                    classification = output.get("classification") or {}
                    yield {
                        "event": "metadata",
                        "data": json.dumps({
                            "type": "classify",
                            "clauses": classification.get("auto_clauses", []),
                            "contract_type": classification.get("contract_type"),
                            "readability": classification.get("readability", {}),
                        }, ensure_ascii=False, default=str),
                    }

                # 风险扫描完成
                elif node_name == "scan_risks":
                    risks = output.get("risks") or {}
                    yield {
                        "event": "metadata",
                        "data": json.dumps({
                            "type": "risks",
                            "meso_issues": risks.get("meso_issues", []),
                            "micro_issues": risks.get("micro_issues", []),
                            "loopholes": risks.get("loopholes", []),
                            "missing_clauses": risks.get("missing_clauses", []),
                        }, ensure_ascii=False, default=str),
                    }

                # 报告生成中
                elif node_name == "generate_report":
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "node": node_name,
                            "content": output.get("report", "")[:200],
                        }, ensure_ascii=False),
                    }

                # 最终汇总
                elif node_name == "finalize":
                    structured = output.get("structured_review") or {}
                    yield {
                        "event": "done",
                        "data": json.dumps({
                            "status": "completed",
                            "summary": output.get("summary", {}),
                            "report": output.get("report", ""),
                            "structured_review": structured,
                        }, ensure_ascii=False, default=str),
                    }

        except Exception as e:
            logger.exception("Contract review stream error")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator(), ping=SSE_PING_INTERVAL, sep="\n")


@router.post("/contract/draft-clause")
async def draft_contract_clause(
    body: dict,
    user: dict = Depends(check_rate_limit),
):
    from ..services.agents import ContractReviewSkill
    from ..core.llm_client import get_llm_client

    llm_client = get_llm_client()
    llm = llm_client.get_chat_model(model="deepseek-v4-pro", temperature=0.5, max_tokens=2048)

    skill = ContractReviewSkill(llm)
    result = await skill.draft_clause(
        clause_type=body.get("clause_type", ""),
        context=body.get("context", ""),
        user_position=body.get("user_position", "乙方"),
    )

    return {"clause": result}
