from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum

class TypeEnum(str, enum.Enum):
    problem = "problem"
    note = "note"
    emergency = "emergency"

class StatusEnum(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"
    reopened = "reopened"

class RoleEnum(str, enum.Enum):
    admin = "admin"
    user = "user"

class NotificationTypeEnum(str, enum.Enum):
    critical_issue = "critical_issue"
    overdue_issue = "overdue_issue"
    ai_alert = "ai_alert"
    issue_closed = "issue_closed"
    new_comment = "new_comment"

class UserStatusEnum(str, enum.Enum):
    unverified = "unverified"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class CategoryEnum(str, enum.Enum):
    lab = "lab"
    filling = "filling"
    production = "production"
    admin = "admin"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(RoleEnum), default=RoleEnum.user)
    status = Column(Enum(UserStatusEnum), default=UserStatusEnum.pending)
    permissions = Column(Text, default='{"can_add": true, "can_delete": false, "can_edit_permissions": false}')
    category = Column(Enum(CategoryEnum), nullable=True)
    reset_code = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    issues = relationship("Issue", back_populates="creator")
    comments = relationship("Comment", back_populates="author")

class Issue(Base):
    __tablename__ = "issues"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    type = Column(Enum(TypeEnum), nullable=False)
    status = Column(Enum(StatusEnum), default=StatusEnum.open)
    category = Column(String, nullable=False)  # legacy single category
    categories = Column(JSON, default=list)   # NEW: multi-category support
    media_url = Column(String, nullable=True)
    media_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    is_archived = Column(Boolean, default=False, nullable=False)
    creator_id = Column(Integer, ForeignKey("users.id"))
    creator = relationship("User", back_populates="issues")
    comments = relationship("Comment", back_populates="issue", cascade="all, delete")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    author_id = Column(Integer, ForeignKey("users.id"))
    issue_id = Column(Integer, ForeignKey("issues.id"))
    author = relationship("User", back_populates="comments")
    issue = relationship("Issue", back_populates="comments")

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    type = Column(Enum(NotificationTypeEnum), nullable=False)
    is_read = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    issue_id = Column(Integer, ForeignKey("issues.id"), nullable=True)
