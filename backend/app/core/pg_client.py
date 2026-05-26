"""
PostgreSQL + pgvector 三库架构 — 法官库 / 律师库 / 法条库

judge_db: 裁判文书、判例、量刑标准、审判流程
lawyer_db: 辩护策略、证据规则、合同审查模板、代理词
law_db: 法律法规、司法解释、部门规章
"""
import logging
from datetime import date, datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Integer, String, Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings

logger = logging.getLogger(__name__)

# ============================================================
# 三库独立引擎
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

ENGINES = {
    "judge": judge_engine,
    "lawyer": lawyer_engine,
    "law": law_engine,
}


class Base(DeclarativeBase):
    pass


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
# 生命周期管理
# ============================================================

async def init_pg():
    """初始化三库连接池并建表"""
    for name, engine in ENGINES.items():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[%s] 数据库连接池初始化完成", name)


async def close_pg():
    """关闭三库连接池"""
    for name, engine in ENGINES.items():
        await engine.dispose()
        logger.info("[%s] 数据库连接池已关闭", name)


# ============================================================
# 法官库检索
# ============================================================

async def search_judge_cases_by_vector(
    query_embedding: list[float],
    top_k: int = 5,
    case_type: Optional[str] = None,
) -> list[dict]:
    """向量检索裁判文书"""
    async with AsyncSession(judge_engine) as session:
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
    async with AsyncSession(judge_engine) as session:
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
    async with AsyncSession(lawyer_engine) as session:
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
    async with AsyncSession(lawyer_engine) as session:
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
    async with AsyncSession(lawyer_engine) as session:
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
    async with AsyncSession(law_engine) as session:
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
    async with AsyncSession(law_engine) as session:
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
    async with AsyncSession(law_engine) as session:
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
