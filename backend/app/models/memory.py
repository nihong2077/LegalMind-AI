from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ..core.database import Base


class Memory(Base):
    """记忆模型 - 用于存储用户的历史对话和案件记忆"""
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    memory_type = Column(String(50), default="general")  # general, case_specific, preference
    content = Column(Text, nullable=False)
    metadata = Column(JSON, default=dict)
    relevance_score = Column(Integer, default=50)  # 0-100, 用于记忆检索排序
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="memories")
    case = relationship("Case", back_populates="memories")

    def __repr__(self):
        return f"<Memory {self.id}>"
