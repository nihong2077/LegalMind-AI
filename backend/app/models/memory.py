from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from ..core.database import Base


class Memory(Base):
    """记忆模型 - 用于存储用户的历史对话和案件记忆"""
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    memory_type = Column(String(50), default="general", index=True)  # general, case_specific, preference
    content = Column(Text, nullable=False)
    memory_metadata = Column(JSON, default=dict)
    relevance_score = Column(Integer, default=50, index=True)  # 0-100, 用于记忆检索排序
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    # 关系
    user = relationship("User", back_populates="memories")
    case = relationship("Case", back_populates="memories")

    def __repr__(self):
        return f"<Memory {self.id}>"
