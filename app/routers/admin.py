from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import User, Issue, RoleEnum, UserStatusEnum, CategoryEnum
from app.schemas import UserOut, IssueOut, ApproveUserRequest, CategoryEnum
from app.auth import require_admin, get_current_user
from pydantic import BaseModel
from typing import Optional
import json

router = APIRouter(prefix="/admin", tags=["Admin"])

class UpdateRoleRequest(BaseModel):
    role: RoleEnum

class UpdateStatusRequest(BaseModel):
    status: str

class UpdatePermissionsRequest(BaseModel):
    permissions: str

class UpdateIssueRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None

@router.get("/users", response_model=list[UserOut])
def get_all_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return db.query(User).order_by(User.created_at.desc()).all()

@router.patch("/users/{user_id}/role", response_model=UserOut)
def update_user_role(user_id: int, data: UpdateRoleRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    user.role = data.role
    db.commit()
    db.refresh(user)
    return user

@router.patch("/users/{user_id}/status", response_model=UserOut)
def update_user_status(user_id: int, data: UpdateStatusRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.status = data.status
    db.commit()
    db.refresh(user)
    return user

@router.post("/users/{user_id}/approve", response_model=UserOut)
def approve_user(user_id: int, data: ApproveUserRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.category == CategoryEnum.admin:
        user.role = RoleEnum.admin
    else:
        user.role = RoleEnum.user
    user.status = UserStatusEnum.approved
    user.category = data.category
    db.commit()
    db.refresh(user)
    return user

@router.post("/users/{user_id}/reject", response_model=UserOut)
def reject_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.status = UserStatusEnum.rejected
    db.commit()
    db.refresh(user)
    return user

@router.patch("/users/{user_id}/permissions", response_model=UserOut)
def update_user_permissions(user_id: int, data: UpdatePermissionsRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    admin_perms = json.loads(admin.permissions or "{}")
    if not admin_perms.get("can_edit_permissions"):
        raise HTTPException(status_code=403, detail="لا تملك صلاحية تعديل الصلاحيات")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.permissions = data.permissions
    db.commit()
    db.refresh(user)
    return user

@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}

@router.delete("/issues/{issue_id}")
def delete_issue(issue_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    db.delete(issue)
    db.commit()
    return {"message": "Issue deleted"}

@router.patch("/issues/{issue_id}", )
def update_issue(issue_id: int, data: UpdateIssueRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    if data.title: issue.title = data.title
    if data.description: issue.description = data.description
    if data.type: issue.type = data.type
    db.commit()
    db.refresh(issue)
    return issue

@router.get("/archived-issues", response_model=list[IssueOut])
def get_archived_issues(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return db.query(Issue).filter(Issue.is_archived == True).order_by(Issue.created_at.desc()).all()

@router.patch("/issues/{issue_id}/archive", response_model=IssueOut)
def archive_issue(issue_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue.is_archived = True
    db.commit()
    db.refresh(issue)
    return issue
