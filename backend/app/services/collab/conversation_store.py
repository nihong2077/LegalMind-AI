"""
协同会话存储层（T1.1）

PostgreSQL（legalmind_app）为权威源，Redis 只做热缓存。
为便于在无 DB 环境下做业务逻辑单测，会话/成员/消息的存取抽象为
``ConversationStore`` 协议；生产用 ``PgConversationStore``（SQLAlchemy ORM），
测试可注入内存实现。后续 T1.6 runner 复用同一接口。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.errors import ConflictError, InvalidParamsError, NotFoundError
from ...core.pg_client import (
    AgentRegistry,
    Conversation,
    ConversationMember,
    Message,
    CaseRosterTemplate,
    app_session_factory,
)

# 单聊默认 Agent（与 05-seed 种子一致）
DEFAULT_DIRECT_AGENT = "general_assistant"
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


# ============================================================
# 序列化
# ============================================================

def _dt(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def serialize_agent(agent: AgentRegistry) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "avatar": agent.avatar,
        "role_label": agent.role_label,
        "description": agent.description,
        "skill_ref": agent.skill_ref,
        "persona": agent.persona,
        "model_pref": agent.model_pref or {},
        "is_tool": agent.is_tool,
        "sort_order": agent.sort_order,
        "enabled": agent.enabled,
    }


def serialize_member(member: ConversationMember, agent: Optional[AgentRegistry] = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "agent_id": member.agent_id,
        "role": member.role,  # host / member
        "is_auto": member.is_auto,
        "joined_at": _dt(member.joined_at),
    }
    if agent is not None:
        data.update(
            name=agent.name,
            avatar=agent.avatar,
            role_label=agent.role_label,
            is_tool=agent.is_tool,
            sort_order=agent.sort_order,
        )
    return data


def serialize_conversation(
    conv: Conversation,
    members: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    return {
        "id": str(conv.id),
        "user_id": conv.user_id,
        "type": conv.type,
        "case_type": conv.case_type,
        "title": conv.title,
        "status": conv.status,
        "my_role": conv.my_role,
        "target_agent_id": conv.target_agent_id,
        "created_at": _dt(conv.created_at),
        "updated_at": _dt(conv.updated_at),
        "members": members or [],
    }


def serialize_message(message: Message) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "sender_type": message.sender_type,
        "sender_id": message.sender_id,
        "sender_name": message.sender_name,
        "content": message.content,
        "msg_type": message.msg_type,
        "round": message.round,
        "event_key": message.event_key,
        "fork_parent_message_id": (
            str(message.fork_parent_message_id)
            if message.fork_parent_message_id is not None
            else None
        ),
        "metadata": message.msg_metadata or {},
        "created_at": _dt(message.created_at),
    }


# ============================================================
# Store 协议
# ============================================================

class ConversationStore(Protocol):
    async def list_conversations(self, user_id: str, status: Optional[str] = None) -> list[dict]: ...

    async def create_conversation(
        self,
        user_id: str,
        conv_type: str,
        case_type: Optional[str],
        title: Optional[str],
        extra_agent_ids: list[str],
        my_role: Optional[str] = None,
        target_agent_id: Optional[str] = None,
    ) -> dict: ...

    async def get_conversation(self, conversation_id: str) -> Optional[dict]: ...

    async def update_conversation(
        self,
        conversation_id: str,
        *,
        title: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict: ...

    async def set_my_role(
        self, conversation_id: str, my_role: Optional[str]
    ) -> Optional[dict]: ...

    async def add_member(self, conversation_id: str, agent_id: str, is_auto: bool) -> dict: ...

    async def remove_member(self, conversation_id: str, agent_id: str) -> bool: ...

    async def list_messages_page(
        self, conversation_id: str, before_id: Optional[str], limit: int
    ) -> tuple[list[dict], Optional[str]]: ...

    async def insert_message(
        self,
        conversation_id: str,
        *,
        sender_type: str,
        sender_id: str,
        sender_name: Optional[str],
        content: str,
        msg_type: str,
        round: int,
        metadata: Optional[dict],
        created_at: Optional[datetime] = None,
    ) -> dict: ...

    async def insert_message_once(
        self,
        conversation_id: str,
        *,
        event_key: str,
        sender_type: str,
        sender_id: str,
        sender_name: Optional[str],
        content: str,
        msg_type: str,
        round: int,
        metadata: Optional[dict],
    ) -> Optional[dict]: ...

    async def get_message_by_event_key(
        self, conversation_id: str, event_key: str
    ) -> Optional[dict]: ...

    async def get_agent(self, agent_id: str) -> Optional[dict]: ...

    async def get_template(self, case_type: str) -> Optional[dict]: ...


# ============================================================
# PostgreSQL 实现
# ============================================================

class PgConversationStore:
    """每个方法一个短事务（async_session_factory 上下文自动关闭）。"""

    async def _load_members(self, session: AsyncSession, conversation_id: uuid.UUID) -> list[dict]:
        stmt = (
            select(ConversationMember, AgentRegistry)
            .outerjoin(AgentRegistry, AgentRegistry.agent_id == ConversationMember.agent_id)
            .where(ConversationMember.conversation_id == conversation_id)
        )
        rows = (await session.execute(stmt)).all()
        members = [serialize_member(m, a) for m, a in rows]
        # 主持人置顶，其余按注册表 sort_order（无注册表信息的排末尾）
        members.sort(key=lambda m: (m["role"] != "host", m.get("sort_order", 10_000)))
        return members

    async def list_conversations(self, user_id: str, status: Optional[str] = None) -> list[dict]:
        async with app_session_factory() as session:
            stmt = select(Conversation).where(Conversation.user_id == user_id)
            if status:
                stmt = stmt.where(Conversation.status == status)
            stmt = stmt.order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
            convs = (await session.execute(stmt)).scalars().all()
            result = []
            for conv in convs:
                members = await self._load_members(session, conv.id)
                result.append(serialize_conversation(conv, members))
            return result

    async def create_conversation(
        self,
        user_id: str,
        conv_type: str,
        case_type: Optional[str],
        title: Optional[str],
        extra_agent_ids: list[str],
        my_role: Optional[str] = None,
        target_agent_id: Optional[str] = None,
    ) -> dict:
        async with app_session_factory() as session:
            # 1. 确定 roster：模板（host + roster）或单聊目标 Agent（B1）
            host_id: Optional[str] = None
            roster_ids: list[str] = []
            if case_type:
                tpl_row = await session.get(CaseRosterTemplate, case_type)
                if tpl_row is None or not tpl_row.enabled:
                    raise InvalidParamsError(f"未知或已停用的案情模板：{case_type}")
                host_id = tpl_row.host_agent_id
                roster = sorted(tpl_row.roster or [], key=lambda x: (x.get("stage") != "opening", x.get("order", 99)))
                roster_ids = [item["agent_id"] for item in roster if item.get("agent_id")]
                title = title or tpl_row.name
            elif conv_type == "direct":
                roster_ids = [target_agent_id or DEFAULT_DIRECT_AGENT]
            # 去重保序：模板成员 + 用户追加；host 一定在列
            seen: set[str] = set()
            ordered: list[str] = []
            for agent_id in [*roster_ids, *(extra_agent_ids or [])]:
                if agent_id and agent_id not in seen:
                    seen.add(agent_id)
                    ordered.append(agent_id)
            if host_id and host_id not in seen:
                ordered.insert(0, host_id)
                seen.add(host_id)
            if not ordered:
                raise InvalidParamsError("创建群聊必须选择至少一个 Agent 或指定案情模板")

            # B3：用户扮演的角色必须 ∈ 最终 roster（不扮演时为空）
            if my_role and my_role not in seen:
                raise InvalidParamsError(f"my_role 不在会话成员中：{my_role}")

            # 2. 校验所有 Agent 存在且启用
            agents: dict[str, AgentRegistry] = {}
            for agent_id in ordered:
                agent = await session.get(AgentRegistry, agent_id)
                if agent is None or not agent.enabled:
                    raise InvalidParamsError(f"Agent 不存在或已停用：{agent_id}")
                agents[agent_id] = agent

            # 3. 建会话 + 成员（模板来源 is_auto=true，手动追加 is_auto=false）
            conv = Conversation(
                user_id=user_id,
                type=conv_type,
                case_type=case_type,
                title=title,
                status="active",
                my_role=my_role,
                target_agent_id=target_agent_id,
            )
            session.add(conv)
            await session.flush()
            auto_set = set(roster_ids)
            if host_id:
                auto_set.add(host_id)
            for agent_id in ordered:
                session.add(
                    ConversationMember(
                        conversation_id=conv.id,
                        agent_id=agent_id,
                        role="host" if agent_id == host_id else "member",
                        is_auto=agent_id in auto_set,
                    )
                )
            await session.commit()
            await session.refresh(conv)
            members = await self._load_members(session, conv.id)
            return serialize_conversation(conv, members)

    async def get_conversation(self, conversation_id: str) -> Optional[dict]:
        async with app_session_factory() as session:
            conv = await session.get(Conversation, self._uuid(conversation_id))
            if conv is None:
                return None
            members = await self._load_members(session, conv.id)
            return serialize_conversation(conv, members)

    async def update_conversation(
        self,
        conversation_id: str,
        *,
        title: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        async with app_session_factory() as session:
            conv = await session.get(Conversation, self._uuid(conversation_id))
            if conv is None:
                raise NotFoundError("会话不存在")
            if title is not None:
                conv.title = title
            if status is not None:
                conv.status = status
            await session.commit()
            await session.refresh(conv)
            members = await self._load_members(session, conv.id)
            return serialize_conversation(conv, members)

    async def set_my_role(
        self, conversation_id: str, my_role: Optional[str]
    ) -> Optional[dict]:
        """设置/撤销用户扮演角色（``None`` ＝撤销接管，B2「交还给 AI」跨轮持久化）。"""
        async with app_session_factory() as session:
            conv = await session.get(Conversation, self._uuid(conversation_id))
            if conv is None:
                return None
            conv.my_role = my_role
            await session.commit()
            await session.refresh(conv)
            members = await self._load_members(session, conv.id)
            return serialize_conversation(conv, members)

    async def add_member(self, conversation_id: str, agent_id: str, is_auto: bool) -> dict:
        async with app_session_factory() as session:
            conv_id = self._uuid(conversation_id)
            conv = await session.get(Conversation, conv_id)
            if conv is None:
                raise NotFoundError("会话不存在")
            agent = await session.get(AgentRegistry, agent_id)
            if agent is None or not agent.enabled:
                raise InvalidParamsError(f"Agent 不存在或已停用：{agent_id}")
            existing = (
                await session.execute(
                    select(ConversationMember).where(
                        and_(
                            ConversationMember.conversation_id == conv_id,
                            ConversationMember.agent_id == agent_id,
                        )
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise ConflictError(f"Agent 已在会话中：{agent_id}")
            member = ConversationMember(
                conversation_id=conv_id,
                agent_id=agent_id,
                role="member",
                is_auto=is_auto,
            )
            session.add(member)
            await session.commit()
            await session.refresh(member)
            return serialize_member(member, agent)

    async def remove_member(self, conversation_id: str, agent_id: str) -> bool:
        async with app_session_factory() as session:
            conv_id = self._uuid(conversation_id)
            member = (
                await session.execute(
                    select(ConversationMember).where(
                        and_(
                            ConversationMember.conversation_id == conv_id,
                            ConversationMember.agent_id == agent_id,
                        )
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                return False
            await session.delete(member)
            await session.commit()
            return True

    async def list_messages_page(
        self, conversation_id: str, before_id: Optional[str], limit: int
    ) -> tuple[list[dict], Optional[str]]:
        """游标分页：取比 before 更早的一页（按时间倒序取，返回时转成正序）。

        ``next_before`` 为当前页最旧消息 id，前端继续上拉时作为下次的 before。
        """
        limit = max(1, min(limit, MAX_PAGE_LIMIT))
        async with app_session_factory() as session:
            conv_id = self._uuid(conversation_id)
            stmt = select(Message).where(Message.conversation_id == conv_id)
            if before_id:
                anchor = await session.get(Message, self._uuid(before_id))
                if anchor is not None:
                    stmt = stmt.where(
                        or_(
                            Message.created_at < anchor.created_at,
                            and_(
                                Message.created_at == anchor.created_at,
                                Message.id < anchor.id,
                            ),
                        )
                    )
            stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
            rows = list((await session.execute(stmt)).scalars().all())
            has_more = len(rows) > limit
            page = rows[:limit]
            next_before = str(page[-1].id) if has_more and page else None
            messages = [serialize_message(m) for m in reversed(page)]
            return messages, next_before

    async def insert_message(
        self,
        conversation_id: str,
        *,
        sender_type: str,
        sender_id: str,
        sender_name: Optional[str],
        content: str,
        msg_type: str,
        round: int,
        metadata: Optional[dict],
        created_at: Optional[datetime] = None,
    ) -> dict:
        async with app_session_factory() as session:
            conv_id = self._uuid(conversation_id)
            conv = await session.get(Conversation, conv_id)
            if conv is None:
                raise NotFoundError("会话不存在")
            fields: dict[str, Any] = {
                "conversation_id": conv_id,
                "sender_type": sender_type,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "content": content,
                "msg_type": msg_type,
                "round": round,
                "msg_metadata": metadata or {},
            }
            # 迁移历史消息时保留原始时间戳；缺省走 server_default（now()）
            if created_at is not None:
                fields["created_at"] = created_at
            message = Message(**fields)
            session.add(message)
            # 顺手刷新会话排序时间
            conv.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(message)
            return serialize_message(message)

    async def insert_message_once(
        self,
        conversation_id: str,
        *,
        event_key: str,
        sender_type: str,
        sender_id: str,
        sender_name: Optional[str],
        content: str,
        msg_type: str,
        round: int,
        metadata: Optional[dict],
    ) -> Optional[dict]:
        """幂等写入：``INSERT ... ON CONFLICT (event_key) DO NOTHING``。

        返回 None 表示该 ``event_key`` 已存在（重跑/恢复场景，不重复落库/推送）。
        """
        async with app_session_factory() as session:
            conv_id = self._uuid(conversation_id)
            conv = await session.get(Conversation, conv_id)
            if conv is None:
                raise NotFoundError("会话不存在")
            stmt = (
                pg_insert(Message)
                .values(
                    conversation_id=conv_id,
                    sender_type=sender_type,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    content=content,
                    msg_type=msg_type,
                    round=round,
                    event_key=event_key,
                    msg_metadata=metadata or {},
                )
                .on_conflict_do_nothing(index_elements=["event_key"])
                .returning(Message.id)
            )
            inserted_id = (await session.execute(stmt)).scalar_one_or_none()
            if inserted_id is None:
                await session.rollback()
                return None
            conv.updated_at = datetime.now(timezone.utc)
            await session.commit()
            message = await session.get(Message, inserted_id)
            return serialize_message(message)

    async def get_message_by_event_key(
        self, conversation_id: str, event_key: str
    ) -> Optional[dict]:
        """按确定性幂等键查已落库消息（"先查库后发"）。"""
        async with app_session_factory() as session:
            conv_id = self._uuid(conversation_id)
            stmt = select(Message).where(
                and_(
                    Message.conversation_id == conv_id,
                    Message.event_key == event_key,
                )
            )
            message = (await session.execute(stmt)).scalar_one_or_none()
            return serialize_message(message) if message is not None else None

    async def get_agent(self, agent_id: str) -> Optional[dict]:
        async with app_session_factory() as session:
            agent = await session.get(AgentRegistry, agent_id)
            return serialize_agent(agent) if agent is not None else None

    async def get_template(self, case_type: str) -> Optional[dict]:
        async with app_session_factory() as session:
            tpl = await session.get(CaseRosterTemplate, case_type)
            if tpl is None:
                return None
            return {
                "case_type": tpl.case_type,
                "name": tpl.name,
                "icon": tpl.icon,
                "description": tpl.description,
                "host_agent_id": tpl.host_agent_id,
                "roster": tpl.roster or [],
                "max_rounds": tpl.max_rounds,
                "opening_enabled": tpl.opening_enabled,
                "minutes_enabled": tpl.minutes_enabled,
                "adapter": tpl.adapter,
                "enabled": tpl.enabled,
            }

    @staticmethod
    def _uuid(value: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            raise NotFoundError("资源不存在")


# 进程级单例（路由依赖默认注入；测试可 override）
pg_store = PgConversationStore()
