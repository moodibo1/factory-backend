from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models.models import User, UserStatusEnum
from app.schemas import UserCreate, UserOut, Token
from app.auth import hash_password, verify_password, create_token, get_current_user
from datetime import datetime, timedelta
import json, os, uuid, requests

router = APIRouter(prefix="/auth", tags=["Auth"])


def send_verification_email(to_email: str, code: str):
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_role_key:
        print("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing — email not sent")
        return

    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
        <h2>رسالة تحقق من نظام المصنع</h2>
        <p>رمز التحقق الخاص بك هو:</p>
        <h1 style="color: #6a0dad; letter-spacing: 5px;">{code}</h1>
        <p>يرجى إدخاله في النظام لإكمال التسجيل. ينتهي خلال 15 دقيقة.</p>
    </div>
    """

    response = requests.post(
        f"{supabase_url}/functions/v1/send-email",
        headers={
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
        json={"to": to_email, "subject": "رمز التحقق - نظام المصنع", "html": html},
        timeout=10,
    )
    print(f"Supabase email response: {response.status_code} — {response.text}")


class VerifyEmailRequest(BaseModel):
    email: str
    code: str


@router.post("/register")
def register(data: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    verify_code = str(uuid.uuid4()).split('-')[0].upper()
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    existing = db.query(User).filter(User.email == data.email).first()

    if existing:
        if existing.status != UserStatusEnum.unverified:
            raise HTTPException(status_code=400, detail="Email already registered")
        # Unverified — overwrite code and resend
        existing.hashed_password = hash_password(data.password)
        existing.name = data.name
        existing.verification_code = verify_code
        existing.token_expires_at = expires_at
        db.commit()
    else:
        new_user = User(
            name=data.name,
            email=data.email,
            hashed_password=hash_password(data.password),
            status=UserStatusEnum.unverified,
            verification_code=verify_code,
            token_expires_at=expires_at,
            permissions=json.dumps({"can_add": True, "can_delete": False, "can_edit_permissions": False})
        )
        db.add(new_user)
        db.commit()

    print(f"VERIFICATION CODE for {data.email}: {verify_code}")
    background_tasks.add_task(send_verification_email, data.email, verify_code)
    return {"message": "Verification code sent to email"}


@router.post("/verify-email")
def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.status != UserStatusEnum.unverified:
        return {"message": "Already verified"}

    if user.verification_code != data.code.strip().upper():
        raise HTTPException(status_code=400, detail="Invalid verification code")

    if user.token_expires_at and user.token_expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Verification code expired")

    user.status = UserStatusEnum.pending
    user.verification_code = None
    user.token_expires_at = None
    db.commit()

    return {"message": "Email verified. Awaiting admin approval."}


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form.username.strip().lower()
    user = db.query(User).filter(User.email.ilike(email)).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.status == UserStatusEnum.unverified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")

    if user.status == UserStatusEnum.pending:
        raise HTTPException(status_code=403, detail="PENDING")

    if user.status == UserStatusEnum.rejected:
        raise HTTPException(status_code=403, detail="REJECTED")

    token = create_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
