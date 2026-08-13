from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.models import Issue, Comment, StatusEnum, User
from app.schemas import IssueOut, CommentCreate, CommentOut
from app.auth import get_current_user, require_admin
from app.models.models import TypeEnum, CategoryEnum
import shutil, os, uuid, json
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
        # Normal users see issues published to their specific category
        user_cat = current_user.category.value if current_user.category else None
        if user_cat:
            from sqlalchemy import cast, String
            q = q.filter(
                (cast(Issue.categories, String).like(f'%"{user_cat}"%')) | 
                (Issue.category == user_cat)
            )
        else:
            return []
    
    if category:
        q = q.filter(Issue.category == category)
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
        user_cat = current_user.category.value if current_user.category else None
        if user_cat:
            from sqlalchemy import cast, String
            q = q.filter(
                (cast(Issue.categories, String).like(f'%"{user_cat}"%')) | 
                (Issue.category == user_cat)
            )
        else:
            return {"total": 0}
            
    if category:
        q = q.filter(Issue.category == category)
    if creator_id:
        q = q.filter(Issue.creator_id == creator_id)
    return {"total": q.count()}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "mp4", "mov"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024   # 10MB
MAX_VIDEO_SIZE = 50 * 1024 * 1024   # 50MB

@router.post("/", response_model=IssueOut)
def create_issue(
    title: str = Form(...),
    description: Optional[str] = Form(None),
    type: TypeEnum = Form(...),
    category: str = Form(...),
    categories: Optional[str] = Form(None),  # JSON string of categories array for cross-posting
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    media_url = None
    media_type = None

    # === CATEGORY VALIDATION ===
    if current_user.role != "admin":
        user_category = current_user.category.value if current_user.category else None
        if not user_category:
            raise HTTPException(status_code=403, detail="Your account has no assigned category")
        if category != user_category:
            raise HTTPException(status_code=403, detail=f"You can only post to your assigned category: {user_category}")
        issue_categories = [user_category]
        issue_primary_category = user_category
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
        # Validate file extension
        ext = file.filename.split(".")[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"نوع الملف غير مسموح. الأنواع المسموحة: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        # Validate MIME type
        is_image = file.content_type in ALLOWED_IMAGE_TYPES
        is_video = file.content_type in ALLOWED_VIDEO_TYPES
        if not is_image and not is_video:
            raise HTTPException(
                status_code=400,
                detail="نوع الملف غير مدعوم. يُسمح فقط بالصور (JPG, PNG, WEBP) ومقاطع الفيديو (MP4, MOV)"
            )

        # Read file content and validate size
        content = file.file.read()
        file_size = len(content)

        if is_image and file_size > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="حجم الصورة كبير جداً. الحد الأقصى 10MB")
        if is_video and file_size > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=400, detail="حجم الفيديو كبير جداً. الحد الأقصى 50MB")

        # Supabase Storage Upload
        filename = f"{uuid.uuid4()}.{ext}"
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        bucket_name = os.getenv("SUPABASE_BUCKET", "media")
        
        if supabase_url and supabase_key:
            # Upload to Supabase Storage Bucket
            import requests
            upload_url = f"{supabase_url}/storage/v1/object/{bucket_name}/{filename}"
            headers = {
                "Authorization": f"Bearer {supabase_key}",
                "apikey": supabase_key,
                "Content-Type": file.content_type
            }
            res = requests.post(upload_url, headers=headers, data=content)
            
            if res.status_code >= 400:
                print(f"Supabase Upload Error: {res.text}")
                raise HTTPException(status_code=500, detail="فشل رفع الملف إلى التخزين السحابي")
                
            media_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{filename}"
        else:
            # Fallback to local storage if Supabase is strictly missing from env
            path = os.path.join(UPLOAD_DIR, filename)
            with open(path, "wb") as f:
                f.write(content)
            media_url = f"/uploads/{filename}"

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
    from datetime import datetime
    issue.status = STATUS_CYCLE[issue.status]
    if issue.status == StatusEnum.closed:
        issue.closed_at = datetime.utcnow()
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
    from datetime import datetime
    issue.status = StatusEnum.closed
    issue.closed_at = datetime.utcnow()
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
    
    # Overwrite the post's categories array entirely with the new selection
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
    comment = Comment(text=data.text, author_id=current_user.id, issue_id=issue_id)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment

@router.get("/{issue_id}/comments", response_model=list[CommentOut])
def get_comments(issue_id: int, db: Session = Depends(get_db)):
    return db.query(Comment).filter(Comment.issue_id == issue_id).all()

class AISearchRequest(BaseModel):
    query: str

@router.post("/ai-search", response_model=list[IssueOut])
async def ai_search(data: AISearchRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # AI Search temporarily disabled - returning all issues
    issues = db.query(Issue).order_by(Issue.created_at.desc()).all()
    return issues
