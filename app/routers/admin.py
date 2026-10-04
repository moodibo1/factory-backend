import json
import os
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User, Issue, RoleEnum, UserStatusEnum, CategoryEnum
from app.schemas import UserOut, IssueOut, ApproveUserRequest
from app.auth import require_admin
from app.maintenance import _run_monthly_archival_and_cleanup, run_bimonthly_cycle, run_emergency_fallback, estimate_storage_usage
from app.services.scheduler import purge_two_month_old_images_job
import requests

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

class MonthlyMaintenanceRequest(BaseModel):
    year: int
    month: int

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

    media_url = issue.media_url
    if media_url:
        try:
            parsed = urlparse(media_url)
            path_parts = [part for part in parsed.path.split('/') if part]
            if len(path_parts) >= 3:
                bucket_name = path_parts[0]
                file_name = '/'.join(path_parts[1:])
                supabase_url = os.getenv('SUPABASE_URL')
                supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
                if supabase_url and supabase_key:
                    delete_url = f"{supabase_url}/storage/v1/object/{bucket_name}/{file_name}"
                    delete_response = requests.delete(
                        delete_url,
                        headers={
                            'Authorization': f"Bearer {supabase_key}",
                            'apikey': supabase_key,
                        },
                    )
                    if delete_response.status_code >= 400:
                        print(f"Supabase Delete Error {delete_response.status_code}: {delete_response.text}")
        except Exception as exc:
            print(f"Issue media removal failed: {exc}")

    db.delete(issue)
    db.commit()
    return

@router.post("/storage/cleanup-orphans")
def cleanup_orphaned_storage_files(db: DbDep, admin: AdminDep):
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    bucket_name = os.getenv('SUPABASE_BUCKET', 'media')

    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Supabase storage configuration is missing")

    live_paths = set()
    issues = db.query(Issue).all()
    for issue in issues:
        if issue.media_url:
            parsed = urlparse(issue.media_url)
            path_parts = [part for part in parsed.path.split('/') if part]
            if len(path_parts) >= 3:
                bucket = path_parts[0]
                if bucket == bucket_name:
                    live_paths.add('/'.join(path_parts[1:]))

    list_url = f"{supabase_url}/storage/v1/object/list/{bucket_name}"
    response = requests.post(
        list_url,
        headers={
            'Authorization': f"Bearer {supabase_key}",
            'apikey': supabase_key,
            'Content-Type': 'application/json',
        },
        json={},
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list storage objects: {response.text}")

    objects = response.json()
    deleted = []
    for obj in objects:
        if isinstance(obj, dict):
            object_path = obj.get('name') or obj.get('path')
            if not object_path:
                continue
            if object_path not in live_paths:
                delete_url = f"{supabase_url}/storage/v1/object/{bucket_name}/{object_path}"
                delete_response = requests.delete(
                    delete_url,
                    headers={
                        'Authorization': f"Bearer {supabase_key}",
                        'apikey': supabase_key,
                    },
                )
                if delete_response.status_code < 400:
                    deleted.append(object_path)
                else:
                    print(f"Cleanup delete failed for {object_path}: {delete_response.status_code} {delete_response.text}")

    return {"deleted": deleted, "count": len(deleted)}

@router.post("/maintenance/monthly-archive-cleanup")
def monthly_archive_cleanup(data: MonthlyMaintenanceRequest, db: DbDep, admin: AdminDep):
    try:
        result = _run_monthly_archival_and_cleanup(data.year, data.month, db)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Monthly archival cleanup failed") from error
    return JSONResponse({
        "year": result["year"],
        "month": result["month"],
        "reports": [
            {
                "id": report.id,
                "department": report.department,
                "file_url": report.file_url,
                "total_issues": report.total_issues,
            }
            for report in result["reports"]
        ],
        "archived_issue_count": result["archived_issue_count"],
        "retention_cutoff": result["retention_cutoff"],
    })

@router.post("/maintenance/trigger-cleanup-now")
def trigger_cleanup_now(admin: AdminDep):
    try:
        return purge_two_month_old_images_job()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Closed issue image purge failed",
        ) from error

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


# ---------------------------------------------------------------------------
# Maintenance: Bi-monthly cycle, emergency fallback, storage status
# ---------------------------------------------------------------------------

@router.post("/maintenance/trigger-bimonthly-cycle")
def trigger_bimonthly_cycle(data: MonthlyMaintenanceRequest, db: DbDep, admin: AdminDep):
    """Force bi-monthly PDF dossier generation + image purge for a given period."""
    try:
        result = run_bimonthly_cycle(data.year, data.month, db)
        return JSONResponse({
            "year": result["year"],
            "month": result["month"],
            "reports": [
                {
                    "id": report.id,
                    "department": report.department,
                    "file_url": report.file_url,
                    "total_issues": report.total_issues,
                }
                for report in result["reports"]
            ],
            "purged_count": result["purged_count"],
            "failed_issue_ids": result["failed_issue_ids"],
            "retention_cutoff": result["retention_cutoff"],
        })
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Bi-monthly cycle failed") from error


@router.post("/maintenance/trigger-emergency-fallback")
def trigger_emergency_fallback(db: DbDep, admin: AdminDep):
    """Manually trigger the storage circuit breaker (emergency FIFO purge)."""
    try:
        return run_emergency_fallback(db, reason="manual_admin_trigger")
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Emergency fallback failed",
        ) from error


@router.get("/maintenance/storage-status")
def get_storage_status(db: DbDep, admin: AdminDep):
    """Return estimated Supabase bucket usage and file counts."""
    try:
        return estimate_storage_usage(db)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to estimate storage usage",
        ) from error