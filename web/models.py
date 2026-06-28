from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class SentinelActionQueue(Base):
    __tablename__ = "sentinel_action_queue"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String, nullable=True)
    action_type = Column(String, nullable=False, default="none")
    threat_detected = Column(Boolean, nullable=False, default=False)
    summary = Column(String, nullable=False)
    raw_ai_output = Column(String, nullable=True)
    payload = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    google_id = Column(String, unique=True, index=True, nullable=True)
    total_points = Column(Integer, default=0)
    total_hours = Column(Integer, default=0)  # <-- Track total hours merged here
    target_trade = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    
    chores = relationship("Chore", back_populates="category")


class Chore(Base):
    __tablename__ = "chores"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    points = Column(Integer, default=10)
    is_active = Column(Boolean, default=True)
    
    category = relationship("Category", back_populates="chores")
    logs = relationship("ChoreLog", back_populates="chore")


class ChoreLog(Base):
    __tablename__ = "chore_logs"

    id = Column(Integer, primary_key=True, index=True)
    chore_id = Column(Integer, ForeignKey("chores.id"), nullable=False)
    completed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    chore = relationship("Chore", back_populates="logs")


class ShiftLog(Base):
    __tablename__ = "shift_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    hours = Column(Integer, nullable=False, default=8)
    task = Column(String, nullable=False)
    engine_check = Column(String, nullable=False)
    photo_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    strategies = relationship("StrategyLog", backref="shift_parent", order_by="StrategyLog.created_at.asc()")


class StrategyLog(Base):
    __tablename__ = "strategy_logs"

    id = Column(Integer, primary_key=True, index=True)
    shift_id = Column(Integer, ForeignKey("shift_logs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    content = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    shift = relationship("ShiftLog", overlaps="shift_parent,strategies")


class DirectorInsight(Base):
    __tablename__ = "director_insights"

    id = Column(Integer, primary_key=True, index=True)
    slot = Column(String, nullable=False)
    content = Column(String, nullable=False)
    summary = Column(String, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())