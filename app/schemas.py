from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from app.models.models import TypeEnum, StatusEnum, RoleEnum, NotificationTypeEnum, UserStatusEnum, CategoryEnum

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: RoleEnum
    status: UserStatusEnum
    permissions: str
    categories:list[CategoryEnum] = []
    created_at: datetime
    class Config: from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class CommentCreate(BaseModel):
    text: str

class CommentOut(BaseModel):
    id: int
    text: str
    author: Optional[UserOut] = None
    created_at: datetime
    class Config: from_attributes = True

class IssueCreate(BaseModel):
    title: str
    description: Optional[str] = None
    type: TypeEnum
    category: str
    categories: Optional[List[str]] = []  # for cross-category sharing by admin

class IssueOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    type: TypeEnum
    status: StatusEnum
    category: str
    in_progress_at: Optional[datetime] = None
    categories: Optional[List[str]] = []
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    is_archived: bool = False
    created_at: datetime
    creator: Optional[UserOut] = None
    comments: list[CommentOut] = []
    class Config: from_attributes = True

class DashboardStats(BaseModel):
    total: int
    open: int
    closed: int
    emergency: int
    by_category: dict

class ApproveUserRequest(BaseModel):
    categories: List[CategoryEnum] = []

# تمت إضافة هذا القالب ليتوافق مع مسار تحديث حالة الموظف
class UpdateStatusRequest(BaseModel):
    status: UserStatusEnum
    categories: Optional[List[CategoryEnum]] = None

class NotificationOut(BaseModel):
    id: int
    title: str
    body: str
    type: NotificationTypeEnum
    is_read: int
    created_at: datetime
    issue_id: Optional[int] = None
    class Config: from_attributes = True