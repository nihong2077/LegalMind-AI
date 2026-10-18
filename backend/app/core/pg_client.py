"""
PostgreSQL + pgvector 四库架构 — 法官库 / 律师库 / 法条库 / 协同应用库

judge_db: 裁判文书、判例、量刑标准、审判流程
lawyer_db: 辩护策略、证据规则、合同审查模板、代理词
law_db: 法律法规、司法解释、部门规章
legalmind_app: 协同会话/成员/消息、Agent 注册表、案情模板、长期记忆、编排台账（D2 独立新库）

注意：知识库模型挂在 Base（含 pgvector Vector 列），应用模型挂在独立的 AppBase；
两套 metadata 绝不混用，否则 create_all 会把 vector 表建进无 vector 扩展的应用库。
"""
import logging
import uuid
from datetime import date, datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings

logger = logging.getLogger(__name__)

# ============================================================
# 四库独立引擎
# ============================================================

judge_engine = create_async_engine(
    settings.PG_JUDGE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

lawyer_engine = create_async_engine(
    settings.PG_LAWYER_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

law_engine = create_async_engine(
    settings.PG_LAW_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

# 协同应用库：连接池单独配置（会话高频短事务）
app_engine = create_async_engine(
    settings.PG_APP_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

# 知识库三引擎（metadata 含 pgvector 表）
ENGINES = {
    "judge": judge_engine,
    "lawyer": lawyer_engine,
    "law": law_engine,
}


# 知识库三库 session factory
judge_session_factory = async_sessionmaker(judge_engine, expire_on_commit=False)
lawyer_session_factory = async_sessionmaker(lawyer_engine, expire_on_commit=False)
law_session_factory = async_sessionmaker(law_engine, expire_on_commit=False)
# 协同应用库 session factory
app_session_factory = async_sessionmaker(app_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """知识库三库 metadata（含 pgvector Vector 列，不可对应用库 create_all）"""


class AppBase(DeclarativeBase):
    """legalmind_app 应用表 metadata（与 sql/init/04-app-schema.sql 对齐）"""


# ============================================================
# judge_db — 法官知识库
# ============================================================

class JudgeCase(Base):
    __tablename__ = "judge_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_number: Mapped[str] = mapped_column(String(128), nullable=False)
    case_name: Mapped[str] = mapped_column(String(512), nullable=False)
    court_level: Mapped[Optional[str]] = mapped_column(String(64))
    court_name: Mapped[Optional[str]] = mapped_column(String(256))
    case_type: Mapped[Optional[str]] = mapped_column(String(64))
    cause_of_action: Mapped[Optional[str]] = mapped_column(String(256))
    judgment_date: Mapped[Optional[date]] = mapped_column()
    plaintiff_claim: Mapped[Optional[str]] = mapped_column(Text)
    defendant_defense: Mapped[Optional[str]] = mapped_column(Text)
    facts_summary: Mapped[Optional[str]] = mapped_column(Text)
    judgment_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    judgment_result: Mapped[Optional[str]] = mapped_column(Text)
    applicable_laws: Mapped[Optional[str]] = mapped_column(Text)
    keywords: Mapped[Optional[list]] = mapped_column(JSON, default=[])
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SentencingGuideline(Base):
    __tablename__ = "sentencing_guidelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crime_category: Mapped[str] = mapped_column(String(256), nullable=False)
    crime_subcategory: Mapped[Optional[str]] = mapped_column(String(256))
    sentencing_range: Mapped[Optional[str]] = mapped_column(String(128))
    aggravating_factors: Mapped[Optional[str]] = mapped_column(Text)
    mitigating_factors: Mapped[Optional[str]] = mapped_column(Text)
    typical_penalty: Mapped[Optional[str]] = mapped_column(Text)
    legal_basis: Mapped[Optional[str]] = mapped_column(Text)
    source_document: Mapped[Optional[str]] = mapped_column(String(512))
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TrialProcedure(Base):
    __tablename__ = "trial_procedures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    procedure_type: Mapped[str] = mapped_column(String(128), nullable=False)
    procedure_name: Mapped[str] = mapped_column(String(256), nullable=False)
    stage: Mapped[Optional[str]] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(Text)
    time_limit: Mapped[Optional[str]] = mapped_column(String(128))
    legal_basis: Mapped[Optional[str]] = mapped_column(Text)
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================
# lawyer_db — 律师知识库
# ============================================================

class DefenseStrategy(Base):
    __tablename__ = "defense_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(256), nullable=False)
    case_type: Mapped[Optional[str]] = mapped_column(String(128))
    applicable_scenario: Mapped[Optional[str]] = mapped_column(Text)
    argument_template: Mapped[Optional[str]] = mapped_column(Text)
    evidence_requirements: Mapped[Optional[str]] = mapped_column(Text)
    success_rate: Mapped[Optional[str]] = mapped_column(String(32))
    reference_cases: Mapped[Optional[str]] = mapped_column(Text)
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EvidenceRule(Base):
    __tablename__ = "evidence_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_name: Mapped[str] = mapped_column(String(256), nullable=False)
    evidence_type: Mapped[Optional[str]] = mapped_column(String(128))
    admissibility_criteria: Mapped[Optional[str]] = mapped_column(Text)
    burden_of_proof: Mapped[Optional[str]] = mapped_column(Text)
    exclusion_rules: Mapped[Optional[str]] = mapped_column(Text)
    legal_basis: Mapped[Optional[str]] = mapped_column(Text)
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ContractReviewTemplate(Base):
    __tablename__ = "contract_review_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_type: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_subtype: Mapped[Optional[str]] = mapped_column(String(128))
    clause_category: Mapped[Optional[str]] = mapped_column(String(128))
    risk_level: Mapped[Optional[str]] = mapped_column(String(16))
    review_checkpoint: Mapped[Optional[str]] = mapped_column(Text)
    suggested_wording: Mapped[Optional[str]] = mapped_column(Text)
    legal_basis: Mapped[Optional[str]] = mapped_column(Text)
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LegalOpinion(Base):
    __tablename__ = "legal_opinions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opinion_type: Mapped[str] = mapped_column(String(128), nullable=False)
    case_type: Mapped[Optional[str]] = mapped_column(String(128))
    title: Mapped[Optional[str]] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    key_arguments: Mapped[Optional[str]] = mapped_column(Text)
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================
# law_db — 法条知识库
# ============================================================

class LegalProvision(Base):
    __tablename__ = "legal_provisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_name: Mapped[str] = mapped_column(String(256), nullable=False)
    law_type: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter: Mapped[Optional[str]] = mapped_column(String(256))
    section: Mapped[Optional[str]] = mapped_column(String(256))
    article_number: Mapped[Optional[str]] = mapped_column(String(64))
    article_title: Mapped[Optional[str]] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[Optional[date]] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="active")
    keywords: Mapped[Optional[list]] = mapped_column(JSON, default=[])
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class JudicialInterpretation(Base):
    __tablename__ = "judicial_interpretations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    interpretation_number: Mapped[Optional[str]] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    issuing_body: Mapped[Optional[str]] = mapped_column(String(256))
    issue_date: Mapped[Optional[date]] = mapped_column()
    effective_date: Mapped[Optional[date]] = mapped_column()
    content: Mapped[str] = mapped_column(Text, nullable=False)
    related_laws: Mapped[Optional[str]] = mapped_column(Text)
    keywords: Mapped[Optional[list]] = mapped_column(JSON, default=[])
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdministrativeRegulation(Base):
    __tablename__ = "administrative_regulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    regulation_name: Mapped[str] = mapped_column(String(512), nullable=False)
    issuing_body: Mapped[Optional[str]] = mapped_column(String(256))
    document_number: Mapped[Optional[str]] = mapped_column(String(128))
    issue_date: Mapped[Optional[date]] = mapped_column()
    effective_date: Mapped[Optional[date]] = mapped_column()
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(128))
    keywords: Mapped[Optional[list]] = mapped_column(JSON, default=[])
    embedding = mapped_column(Vector(1024), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================
# legalmind_app — 协同应用库（与 04-app-schema.sql 对齐）
# ============================================================

class Conversation(AppBase):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # direct/group
    case_type: Mapped[Optional[str]] = mapped_column(String(32))
    title: Mapped[Optional[str]] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # B3：用户扮演的 agent_id（空＝不扮演，仅 group 有效，D11 接管式扮演）
    my_role: Mapped[Optional[str]] = mapped_column(String(64))
    # B1：单聊目标 Agent（仅 direct 有效，T1.5 执行「单聊只调该 Agent」）
    target_agent_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationMember(AppBase):
    __tablename__ = "conversation_members"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")  # host/member
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(AppBase):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user/agent/system
    sender_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sender_name: Mapped[Optional[str]] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    msg_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 确定性幂等键（T1.5）：{turn_id}:r{round}:{agent_id}:{seq}，唯一索引防重复落库
    event_key: Mapped[Optional[str]] = mapped_column(String(128))
    # 时间旅行（F12）：SQL 未加 FK，分支消息可指向任意父消息
    fork_parent_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True))
    msg_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentRegistry(AppBase):
    __tablename__ = "agent_registry"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar: Mapped[Optional[str]] = mapped_column(String(256))
    role_label: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    skill_ref: Mapped[Optional[str]] = mapped_column(String(128))
    persona: Mapped[Optional[str]] = mapped_column(Text)
    model_pref: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_tool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CaseRosterTemplate(AppBase):
    __tablename__ = "case_roster_templates"

    case_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(32))
    description: Mapped[Optional[str]] = mapped_column(Text)
    host_agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    roster: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    max_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    opening_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    minutes_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False, default="generic")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Memory(AppBase):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)  # user/case
    case_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True))
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    source_conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True))
    source_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    embedding_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CollabTurn(AppBase):
    __tablename__ = "collab_turns"

    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # running/interrupted/completed/failed
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="inprocess")
    worker_id: Mapped[Optional[str]] = mapped_column(String(128))
    worker_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_checkpoint_id: Mapped[Optional[str]] = mapped_column(String(128))
    error: Mapped[Optional[dict]] = mapped_column(JSONB)
    forked_from_turn_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class HostDecision(AppBase):
    __tablename__ = "host_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collab_turns.turn_id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    host_agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_output: Mapped[Optional[str]] = mapped_column(Text)
    parsed_directive: Mapped[Optional[dict]] = mapped_column(JSONB)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(64))
    request_id: Mapped[Optional[str]] = mapped_column(String(64))
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ============================================================
# 生命周期管理
# ============================================================

async def init_pg():
    """初始化四库连接池并建表（知识库与应用库使用各自独立的 metadata）"""
    for name, engine in ENGINES.items():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[%s] 数据库连接池初始化完成", name)

    # 应用库：只建 AppBase 的表（权威 schema 见 04-app-schema.sql，create_all 仅补缺）
    async with app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    logger.info("[app] 数据库连接池初始化完成")


async def close_pg():
    """关闭四库连接池"""
    for name, engine in ENGINES.items():
        await engine.dispose()
        logger.info("[%s] 数据库连接池已关闭", name)
    await app_engine.dispose()
    logger.info("[app] 数据库连接池已关闭")


# ============================================================
# 法官库检索
# ============================================================

async def search_judge_cases_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
    case_type: Optional[str] = None,
) -> list[dict]:
    """向量检索裁判文书"""
    async with judge_session_factory() as session:
        stmt = select(
            JudgeCase.id,
            JudgeCase.case_number,
            JudgeCase.case_name,
            JudgeCase.court_name,
            JudgeCase.case_type,
            JudgeCase.facts_summary,
            JudgeCase.judgment_reasoning,
            JudgeCase.judgment_result,
            JudgeCase.embedding.cosine_distance(query_embedding).label("distance"),
        ).where(JudgeCase.embedding.isnot(None))

        if case_type:
            stmt = stmt.where(JudgeCase.case_type == case_type)

        stmt = stmt.order_by(text("distance")).limit(top_k)
        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "case_number": row.case_number,
                "case_name": row.case_name,
                "court_name": row.court_name,
                "case_type": row.case_type,
                "facts_summary": row.facts_summary,
                "judgment_reasoning": row.judgment_reasoning,
                "judgment_result": row.judgment_result,
                "score": 1.0 - float(row.distance),
            }
            for row in rows
        ]


async def search_sentencing_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """向量检索量刑标准"""
    async with judge_session_factory() as session:
        stmt = select(
            SentencingGuideline.id,
            SentencingGuideline.crime_category,
            SentencingGuideline.sentencing_range,
            SentencingGuideline.aggravating_factors,
            SentencingGuideline.mitigating_factors,
            SentencingGuideline.typical_penalty,
            SentencingGuideline.legal_basis,
            SentencingGuideline.embedding.cosine_distance(query_embedding).label("distance"),
        ).where(SentencingGuideline.embedding.isnot(None)).order_by(text("distance")).limit(top_k)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "crime_category": row.crime_category,
                "sentencing_range": row.sentencing_range,
                "aggravating_factors": row.aggravating_factors,
                "mitigating_factors": row.mitigating_factors,
                "typical_penalty": row.typical_penalty,
                "legal_basis": row.legal_basis,
                "score": 1.0 - float(row.distance),
            }
            for row in rows
        ]


# ============================================================
# 律师库检索
# ============================================================

async def search_defense_strategies_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
    case_type: Optional[str] = None,
) -> list[dict]:
    """向量检索辩护策略"""
    async with lawyer_session_factory() as session:
        stmt = select(
            DefenseStrategy.id,
            DefenseStrategy.strategy_name,
            DefenseStrategy.case_type,
            DefenseStrategy.applicable_scenario,
            DefenseStrategy.argument_template,
            DefenseStrategy.evidence_requirements,
            DefenseStrategy.embedding.cosine_distance(query_embedding).label("distance"),
        ).where(DefenseStrategy.embedding.isnot(None))

        if case_type:
            stmt = stmt.where(DefenseStrategy.case_type == case_type)

        stmt = stmt.order_by(text("distance")).limit(top_k)
        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "strategy_name": row.strategy_name,
                "case_type": row.case_type,
                "applicable_scenario": row.applicable_scenario,
                "argument_template": row.argument_template,
                "evidence_requirements": row.evidence_requirements,
                "score": 1.0 - float(row.distance),
            }
            for row in rows
        ]


async def search_evidence_rules_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """向量检索证据规则"""
    async with lawyer_session_factory() as session:
        stmt = select(
            EvidenceRule.id,
            EvidenceRule.rule_name,
            EvidenceRule.evidence_type,
            EvidenceRule.admissibility_criteria,
            EvidenceRule.burden_of_proof,
            EvidenceRule.legal_basis,
            EvidenceRule.embedding.cosine_distance(query_embedding).label("distance"),
        ).where(EvidenceRule.embedding.isnot(None)).order_by(text("distance")).limit(top_k)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "rule_name": row.rule_name,
                "evidence_type": row.evidence_type,
                "admissibility_criteria": row.admissibility_criteria,
                "burden_of_proof": row.burden_of_proof,
                "legal_basis": row.legal_basis,
                "score": 1.0 - float(row.distance),
            }
            for row in rows
        ]


async def search_contract_review_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
    contract_type: Optional[str] = None,
) -> list[dict]:
    """向量检索合同审查模板"""
    async with lawyer_session_factory() as session:
        stmt = select(
            ContractReviewTemplate.id,
            ContractReviewTemplate.contract_type,
            ContractReviewTemplate.clause_category,
            ContractReviewTemplate.risk_level,
            ContractReviewTemplate.review_checkpoint,
            ContractReviewTemplate.suggested_wording,
            ContractReviewTemplate.legal_basis,
            ContractReviewTemplate.embedding.cosine_distance(query_embedding).label("distance"),
        ).where(ContractReviewTemplate.embedding.isnot(None))

        if contract_type:
            stmt = stmt.where(ContractReviewTemplate.contract_type == contract_type)

        stmt = stmt.order_by(text("distance")).limit(top_k)
        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "contract_type": row.contract_type,
                "clause_category": row.clause_category,
                "risk_level": row.risk_level,
                "review_checkpoint": row.review_checkpoint,
                "suggested_wording": row.suggested_wording,
                "legal_basis": row.legal_basis,
                "score": 1.0 - float(row.distance),
            }
            for row in rows
        ]


# ============================================================
# 法条库检索
# ============================================================

async def search_law_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
    law_type: Optional[str] = None,
) -> list[dict]:
    """向量检索法律法规"""
    async with law_session_factory() as session:
        stmt = select(
            LegalProvision.id,
            LegalProvision.law_name,
            LegalProvision.law_type,
            LegalProvision.chapter,
            LegalProvision.article_number,
            LegalProvision.article_title,
            LegalProvision.content,
            LegalProvision.embedding.cosine_distance(query_embedding).label("distance"),
        ).where(
            LegalProvision.embedding.isnot(None),
            LegalProvision.status == "active",
        )

        if law_type:
            stmt = stmt.where(LegalProvision.law_type == law_type)

        stmt = stmt.order_by(text("distance")).limit(top_k)
        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "law_name": row.law_name,
                "law_type": row.law_type,
                "chapter": row.chapter,
                "article_number": row.article_number,
                "article_title": row.article_title,
                "content": row.content,
                "score": 1.0 - float(row.distance),
            }
            for row in rows
        ]


async def search_law_by_keyword(
    keyword: str,
    top_k: int = 10,
    law_type: Optional[str] = None,
) -> list[dict]:
    """关键词全文检索法条"""
    async with law_session_factory() as session:
        stmt = select(
            LegalProvision.id,
            LegalProvision.law_name,
            LegalProvision.law_type,
            LegalProvision.article_number,
            LegalProvision.article_title,
            LegalProvision.content,
        ).where(
            LegalProvision.content.ilike(f"%{keyword}%"),
            LegalProvision.status == "active",
        )

        if law_type:
            stmt = stmt.where(LegalProvision.law_type == law_type)

        stmt = stmt.limit(top_k)
        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "law_name": row.law_name,
                "law_type": row.law_type,
                "article_number": row.article_number,
                "article_title": row.article_title,
                "content": row.content,
                "score": 1.0,
            }
            for row in rows
        ]


async def search_interpretations_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """向量检索司法解释"""
    async with law_session_factory() as session:
        stmt = select(
            JudicialInterpretation.id,
            JudicialInterpretation.title,
            JudicialInterpretation.issuing_body,
            JudicialInterpretation.content,
            JudicialInterpretation.embedding.cosine_distance(query_embedding).label("distance"),
        ).where(JudicialInterpretation.embedding.isnot(None)).order_by(text("distance")).limit(top_k)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "title": row.title,
                "issuing_body": row.issuing_body,
                "content": row.content,
                "score": 1.0 - float(row.distance),
            }
            for row in rows
        ]
