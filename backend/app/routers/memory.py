"""
用户长期记忆 API（P2 T2.1）

- 全部走统一信封（EnvelopeRouter）；
- 以 JWT ``sub``（username）为 user_id 收敛：list/get/patch/delete 均按用户隔离；
- 向量侧（Qdrant ``user_memories``）由 :class:`MemoryStore` 尽力而为维护，失败不阻断 CRUD；
- 记忆召回总开关 ``GET/PUT /api/memories/setting``（关闭后不写不读，T2.3 生效）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from ..core.errors import InvalidParamsError, NotFoundError
from ..core.response import EnvelopeRouter, success
from ..core.security import get_current_user
from ..services.memory.store import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    SCOPES,
    STATUSES,
    MemoryStore,
    get_memory_store,
    is_memory_enabled,
    set_memory_enabled,
)

router = EnvelopeRouter(prefix="/api/memories", tags=["长期记忆"])


async def get_uid(user: dict = Depends(get_current_user)) -> str:
    return user["sub"]


# ============================================================
# 请求模型
# ============================================================

class CreateMemoryRequest(BaseModel):
    scope: str = Field(default="user", pattern="^(user|case)$")
    memory_type: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1)
    summary: Optional[str] = None
    importance: int = Field(default=3, ge=1, le=5)
    case_id: Optional[str] = None
    source_conversation_id: Optional[str] = None
    source_message_id: Optional[str] = None
    starred: bool = False


class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1)
    summary: Optional[str] = None
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    memory_type: Optional[str] = Field(default=None, min_length=1, max_length=32)
    status: Optional[str] = Field(default=None, pattern="^(active|archived)$")
    starred: Optional[bool] = None


class MemoryToggleRequest(BaseModel):
    enabled: bool


# ============================================================
# 总开关（须在 /{memory_id} 之前声明，避免被路径参数吞掉）
# ============================================================

@router.get("/setting")
async def get_memory_setting(uid: str = Depends(get_uid)):
    return success({"enabled": await is_memory_enabled(uid)})


@router.put("/setting")
async def update_memory_setting(
    body: MemoryToggleRequest,
    uid: str = Depends(get_uid),
):
    enabled = await set_memory_enabled(uid, body.enabled)
    return success(
        {"enabled": enabled},
        message="已开启自动记忆" if enabled else "已关闭自动记忆",
    )


# ============================================================
# 记忆 CRUD
# ============================================================

@router.get("")
async def list_memories(
    scope: Optional[str] = Query(default=None),
    memory_type: Optional[str] = Query(default=None),
    case_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    starred: Optional[bool] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    store: MemoryStore = Depends(get_memory_store),
    uid: str = Depends(get_uid),
):
    if scope is not None and scope not in SCOPES:
        raise InvalidParamsError("scope 仅支持 user/case")
    if status is not None and status not in STATUSES:
        raise InvalidParamsError("status 仅支持 active/archived")
    memories, total = await store.list(
        uid,
        scope=scope,
        memory_type=memory_type,
        case_id=case_id,
        status=status,
        starred=starred,
        q=q,
        limit=limit,
        offset=offset,
    )
    return success(
        {"memories": memories, "total": total, "limit": limit, "offset": offset}
    )


@router.post("", status_code=201)
async def create_memory(
    body: CreateMemoryRequest,
    store: MemoryStore = Depends(get_memory_store),
    uid: str = Depends(get_uid),
):
    memory = await store.create(
        uid,
        scope=body.scope,
        memory_type=body.memory_type,
        content=body.content,
        summary=body.summary,
        importance=body.importance,
        case_id=body.case_id,
        source_conversation_id=body.source_conversation_id,
        source_message_id=body.source_message_id,
        starred=body.starred,
    )
    return success(memory, message="记忆已新增")


@router.get("/{memory_id}")
async def get_memory(
    memory_id: str,
    store: MemoryStore = Depends(get_memory_store),
    uid: str = Depends(get_uid),
):
    memory = await store.get(uid, memory_id)
    if memory is None:
        raise NotFoundError("记忆不存在")
    return success(memory)


@router.patch("/{memory_id}")
async def update_memory(
    memory_id: str,
    body: UpdateMemoryRequest,
    store: MemoryStore = Depends(get_memory_store),
    uid: str = Depends(get_uid),
):
    memory = await store.update(
        uid,
        memory_id,
        content=body.content,
        summary=body.summary,
        importance=body.importance,
        memory_type=body.memory_type,
        status=body.status,
        starred=body.starred,
    )
    if memory is None:
        raise NotFoundError("记忆不存在")
    return success(memory, message="记忆已更新")


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    store: MemoryStore = Depends(get_memory_store),
    uid: str = Depends(get_uid),
):
    ok = await store.delete(uid, memory_id)
    if not ok:
        raise NotFoundError("记忆不存在")
    return success({"id": memory_id}, message="记忆已删除")
