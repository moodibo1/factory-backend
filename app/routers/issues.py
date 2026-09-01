from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.models import Issue, Comment, StatusEnum, User, VALID_ISSUE_CATEGORIES
from app.schemas import IssueOut, CommentCreate, CommentOut
from app.auth import get_current_user, require_admin
from app.models.models import TypeEnum, CategoryEnum
from sqlalchemy import cast, String, or_, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
import os, uuid, json, requests
from pydantic import BaseModel

router = APIRouter(prefix="/issues", tags=["Issues"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

STATUS_CYCLE = {
    StatusEnum.open: StatusEnum.in_progress,
    StatusEnum.in_progress: StatusEnum.closed,
    StatusEnum.closed: StatusEnum.reopened,
    StatusEnum.reopened: StatusEnum.in_progress,
}

@router.get("/", response_model=list[IssueOut])
def get_issues(
    category: Optional[str] = None,
    creator_id: Optional[int] = None,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Issue).filter(Issue.is_archived == False)

    # === DATA ISOLATION ===
    if current_user.role != "admin":
        user_categories = [cat.value if hasattr(cat, 'value') else cat for cat in (current_user.categories or [])]
        if user_categories:
            # Use PostgreSQL JSONB array intersection for proper filtering
            conditions = [Issue.category.in_(user_categories)]  # Legacy category field
            # JSONB array intersection: check if any user category exists in issue.categories
            # Use individual OR conditions for each category (simpler and reliable)
            category_conditions = []
            for cat in user_categories:
                category_conditions.append(func.jsonb_exists(Issue.categories, cat))
            if category_conditions:
                conditions.extend(category_conditions)
            q = q.filter(or_(*conditions))
        else:
            return []

    # === FILTERING ===
    if category:
        # Use JSONB operator for categories array and legacy category field
        # Use PostgreSQL jsonb_exists function for proper type handling
        q = q.filter(
            (func.jsonb_exists(Issue.categories, category)) | 
            (Issue.category == category)
        )

    if creator_id:
        q = q.filter(Issue.creator_id == creator_id)

    offset = (page - 1) * limit
    return q.order_by(Issue.created_at.desc()).offset(offset).limit(limit).all()

@router.get("/count")
def get_issues_count(
    category: Optional[str] = None,
    creator_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Issue).filter(Issue.is_archived == False)

    if current_user.role != "admin":
        user_categories = [cat.value if hasattr(cat, 'value') else cat for cat in (current_user.categories or [])]
        if user_categories:
            conditions = []
            for cat in user_categories:
                conditions.append(Issue.category == cat)
            # JSONB array intersection: check if any user category exists in issue.categories  
            # Use individual OR conditions for each category (simpler and reliable)
            category_conditions = []
            for cat in user_categories:
                category_conditions.append(func.jsonb_exists(Issue.categories, cat))
            if category_conditions:
                conditions.extend(category_conditions)
            q = q.filter(or_(*conditions))
        else:
            return {"total": 0}

    if category:
        # Use JSONB operator for categories array and legacy category field
        # ? operator expects JSONB column and text value (not JSONB)
        q = q.filter(
            (Issue.categories.op('?')(category)) | 
            (Issue.category == category)
        )

    if creator_id:
        q = q.filter(Issue.creator_id == creator_id)

    return {"total": q.count()}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "mp4", "mov"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_VIDEO_SIZE = 50 * 1024 * 1024

@router.post("/", response_model=IssueOut)
def create_issue(
    title: str = Form(...),
    description: Optional[str] = Form(None),
    type: TypeEnum = Form(...),
    category: str = Form(...),
    categories: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    media_url = None
    media_type = None

    # === VALIDATE CATEGORY ===
    if category not in VALID_ISSUE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Valid issue categories are: {list(VALID_ISSUE_CATEGORIES)}")

    if current_user.role != "admin":
        user_cats = [c.value if hasattr(c, 'value') else c for c in (current_user.categories or [])]
        if not user_cats:
            raise HTTPException(status_code=403, detail="Your account has no assigned category")
        if category not in user_cats:
            raise HTTPException(status_code=403, detail=f"You can only post to your assigned categories: {user_cats}")
        issue_categories = [category]  # Use only selected category, not all user categories
        issue_primary_category = category
    else:
        issue_primary_category = category
        issue_categories = [category]
        if categories:
            try:
                parsed = json.loads(categories)
                if isinstance(parsed, list) and len(parsed) > 0:
                    issue_categories = parsed
            except:
                pass

    if file and file.filename:
        ext = file.filename.split(".")[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"نوع الملف غير مسموح. الأنواع المسموح بها: {', '.join(ALLOWED_EXTENSIONS)}")

        is_image = file.content_type in ALLOWED_IMAGE_TYPES
        is_video = file.content_type in ALLOWED_VIDEO_TYPES
        if not is_image and not is_video:
            raise HTTPException(status_code=400, detail="نوع الملف غير مدعوم. يسمح فقط بالصور (JPG, PNG, WEBP) ومقاطع الفيديو (MP4, MOV)")

        content = file.file.read()
        file_size = len(content)

        if is_image and file_size > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="حجم الصورة كبير جداً. الحد الأقصى 10MB")
        if is_video and file_size > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=400, detail="حجم الفيديو كبير جداً. الحد الأقصى 50MB")

        filename = f"{uuid.uuid4()}.{ext}"
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        bucket_name = os.getenv("SUPABASE_BUCKET", "media")

        if not supabase_url or not supabase_key:
            raise HTTPException(status_code=500, detail="إعدادات التخزين السحابي غير مكتملة على الخادم")

        upload_url = f"{supabase_url}/storage/v1/object/{bucket_name}/{filename}"
        headers = {
            "Authorization": f"Bearer {supabase_key}",
            "apikey": supabase_key,
            "Content-Type": file.content_type,
        }

        res = requests.post(upload_url, headers=headers, data=content)

        if res.status_code >= 400:
            print(f"Supabase Upload Error {res.status_code}: {res.text}")
            raise HTTPException(status_code=500, detail="فشل رفع الملف إلى التخزين السحابي")

        media_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{filename}"
        media_type = "video" if is_video else "image"

    issue = Issue(
        title=title, description=description,
        type=type, category=issue_primary_category,
        categories=issue_categories,
        media_url=media_url, media_type=media_type,
        creator_id=current_user.id,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue

@router.patch("/{issue_id}/cycle-status", response_model=IssueOut)
def cycle_status(issue_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    from datetime import datetime, timezone
    issue.status = STATUS_CYCLE[issue.status]
    if issue.status == StatusEnum.closed:
        issue.closed_at = datetime.now(timezone.utc)
    elif issue.status == StatusEnum.in_progress:
        issue.closed_at = None
        if issue.in_progress_at is None:
            issue.in_progress_at = datetime.now(timezone.utc)
    else:
        issue.closed_at = None

    db.commit()
    db.refresh(issue)
    return issue

@router.patch("/{issue_id}/close", response_model=IssueOut)
def close_issue(issue_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    from datetime import datetime, timezone

    issue.status = StatusEnum.closed
    issue.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(issue)
    return issue

class ShareIssueRequest(BaseModel):
    categories: list[str]

@router.post("/{issue_id}/share", response_model=IssueOut)
def share_issue(issue_id: int, data: ShareIssueRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if not data.categories:
        raise HTTPException(status_code=400, detail="Must select at least one category")

    issue.categories = data.categories
    db.commit()
    db.refresh(issue)
    return issue

@router.post("/{issue_id}/comments", response_model=CommentOut)
def add_comment(issue_id: int, data: CommentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    # DATA ISOLATION: Check access to this issue
    if current_user.role != "admin":
        user_categories = [cat.value if hasattr(cat, 'value') else cat for cat in (current_user.categories or [])]
        if not user_categories:
            raise HTTPException(status_code=403, detail="Your account has no assigned category")
        if issue.category not in user_categories and not any(c in user_categories for c in (issue.categories or [])):
            raise HTTPException(status_code=403, detail="You do not have access to this issue")
    
    comment = Comment(text=data.text, author_id=current_user.id, issue_id=issue_id)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment

@router.get("/{issue_id}/comments", response_model=list[CommentOut])
def get_comments(
    issue_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    # DATA ISOLATION: Check access to this issue
    if current_user.role != "admin":
        user_categories = [cat.value if hasattr(cat, 'value') else cat for cat in (current_user.categories or [])]
        if not user_categories:
            raise HTTPException(status_code=403, detail="Your account has no assigned category")
        if issue.category not in user_categories and not any(c in user_categories for c in (issue.categories or [])):
            raise HTTPException(status_code=403, detail="You do not have access to this issue")
    
    return db.query(Comment).filter(Comment.issue_id == issue_id).all()

class UpdateIssueRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[TypeEnum] = None

@router.put("/{issue_id}", response_model=IssueOut)
def update_issue(
    issue_id: int,
    data: UpdateIssueRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    # Check ownership: only creator can edit their own issues
    if current_user.id != issue.creator_id:
        raise HTTPException(status_code=403, detail="You can only edit your own issues")
    
    # Update fields if provided
    if data.title is not None:
        issue.title = data.title
    if data.description is not None:
        issue.description = data.description
    if data.type is not None:
        issue.type = data.type
    
    db.commit()
    db.refresh(issue)
    return issue

class AISearchRequest(BaseModel):
    query: str

@router.post("/ai-search", response_model=list[IssueOut])
async def ai_search(data: AISearchRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # DATA ISOLATION: Apply category filtering for non-admin users
    q = db.query(Issue).order_by(Issue.created_at.desc())
    
    if current_user.role != "admin":
        user_categories = [cat.value if hasattr(cat, 'value') else cat for cat in (current_user.categories or [])]
        if user_categories:
            conditions = []
            for cat in user_categories:
                conditions.append(Issue.category == cat)
                conditions.append(cast(Issue.categories, String).like(f'%"{cat}"%'))
            q = q.filter(or_(*conditions))
        else:
            return []
    
    issues = q.all()
    return issues