from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ..core.database import Base


class Case(Base):
    """案件模型"""
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, index=True)
    description = Column(Text)
    status = Column(String(50), default="draft", index=True)  # draft, in_progress, completed
    case_type = Column(String(50), index=True)  # civil, criminal, etc.
    complexity_score = Column(Integer, default=0, index=True)  # 0-100
    case_data = Column(JSON, default=dict)  # 结构化案件数据
    result_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    # 关系
    user = relationship("User", back_populates="cases")
    memories = relationship("Memory", back_populates="case", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Case {self.title}>"
