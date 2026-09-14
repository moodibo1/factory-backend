import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User, Issue, RoleEnum, UserStatusEnum, CategoryEnum
from app.schemas import UserOut, IssueOut, ApproveUserRequest
from app.auth import require_admin

router = APIRouter(prefix="/admin", tags=["Admin"])

# --- التبعيات المشتركة (Dependencies) ---
DbDep = Annotated[Session, Depends(get_db)]
AdminDep = Annotated[User, Depends(require_admin)]

# --- نماذج البيانات (Schemas) ---
class UpdateRoleRequest(BaseModel):
    role: RoleEnum

class UpdateStatusRequest(BaseModel):
    status: UserStatusEnum
    categories: list[CategoryEnum] | None = None  # تم إضافتها لتجنب خطأ AttributeError

class UpdatePermissionsRequest(BaseModel):
    permissions: str

class UpdateIssueRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    type: str | None = None

# --- المسارات (Routes) ---

@router.get("/users", response_model=list[UserOut])
def get_all_users(db: DbDep, admin: AdminDep, skip: int = 0, limit: int = 100):
    return db.query(User).order_by(User.created_at.desc()).offset(skip).limit(limit).all()

@router.patch("/users/{user_id}/role", response_model=UserOut)
def update_user_role(user_id: int, data: UpdateRoleRequest, db: DbDep, admin: AdminDep):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")
    
    user.role = data.role
    db.commit()
    db.refresh(user)
    return user

@router.patch("/users/{user_id}/status", response_model=UserOut)
def update_user_status(user_id: int, data: UpdateStatusRequest, db: DbDep, admin: AdminDep):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    user.status = data.status
    if data.categories is not None:
        user.categories = data.categories
        
    db.commit()
    db.refresh(user)
    return user

@router.post("/users/{user_id}/approve", response_model=UserOut)
def approve_user(user_id: int, data: ApproveUserRequest, db: DbDep, admin: AdminDep):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    if CategoryEnum.admin in data.categories:
        user.role = RoleEnum.admin
    else:
        user.role = RoleEnum.user
        
    user.status = UserStatusEnum.approved
    user.categories = data.categories
    db.commit()
    db.refresh(user)
    return user

@router.post("/users/{user_id}/reject", response_model=UserOut)
def reject_user(user_id: int, db: DbDep, admin: AdminDep):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    user.status = UserStatusEnum.rejected
    db.commit()
    db.refresh(user)
    return user

@router.patch("/users/{user_id}/permissions", response_model=UserOut)
def update_user_permissions(user_id: int, data: UpdatePermissionsRequest, db: DbDep, admin: AdminDep):
    admin_perms = json.loads(admin.permissions or "{}")
    if not admin_perms.get("can_edit_permissions"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا تملك صلاحية تعديل الصلاحيات")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    user.permissions = data.permissions
    db.commit()
    db.refresh(user)
    return user

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: DbDep, admin: AdminDep):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")
        
    db.delete(user)
    db.commit()
    return

@router.delete("/issues/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_issue(issue_id: int, db: DbDep, admin: AdminDep):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
        
    db.delete(issue)
    db.commit()
    return

@router.patch("/issues/{issue_id}", response_model=IssueOut)
def update_issue(issue_id: int, data: UpdateIssueRequest, db: DbDep, admin: AdminDep):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
        
    if data.title is not None: 
        issue.title = data.title
    if data.description is not None: 
        issue.description = data.description
    if data.type is not None: 
        issue.type = data.type
        
    db.commit()
    db.refresh(issue)
    return issue

@router.get("/archived-issues", response_model=list[IssueOut])
def get_archived_issues(db: DbDep, admin: AdminDep, skip: int = 0, limit: int = 100):
    return db.query(Issue).filter(Issue.is_archived == True).order_by(Issue.created_at.desc()).offset(skip).limit(limit).all()

@router.patch("/issues/{issue_id}/archive", response_model=IssueOut)
def archive_issue(issue_id: int, db: DbDep, admin: AdminDep):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
        
    issue.is_archived = True
    db.commit()
    db.refresh(issue)
    return issue