from datetime import datetime, timedelta, timezone
import json
import logging
import os
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
import resend
from sqlalchemy.orm import Session

from app.auth import create_token, get_current_user, hash_password, verify_password
from app.database import get_db
from app.models.models import User, UserStatusEnum
from app.schemas import PasswordResetRequest, PasswordResetVerify, Token, UserCreate, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# ضبط مفتاح Resend عالمياً
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


@router.post("/register")
def register(data: UserCreate, db: Session = Depends(get_db)):
    cleaned_email = data.email.strip().lower()
    existing = db.query(User).filter(User.email == cleaned_email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        name=data.name,
        email=cleaned_email,
        hashed_password=hash_password(data.password),
        status=UserStatusEnum.pending,
        permissions=json.dumps({"can_add": True, "can_delete": False, "can_edit_permissions": False}),
    )
    db.add(new_user)
    db.commit()
    return {"message": "Registration successful, awaiting admin approval"}


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form.username.strip().lower()
    user = db.query(User).filter(User.email.ilike(email)).first()

    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_status = getattr(user, "status", None)
    if user_status == UserStatusEnum.pending or user_status == UserStatusEnum.unverified:
        raise HTTPException(status_code=403, detail="PENDING")

    if user_status == UserStatusEnum.rejected:
        raise HTTPException(status_code=403, detail="REJECTED")

    token = create_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/request-reset")
def request_reset(data: PasswordResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.strip().lower()).first()
    if user:
        otp = "".join(secrets.choice(string.digits) for _ in range(6))
        user.reset_code = otp
        user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        try:
            if not resend.api_key:
                resend.api_key = os.getenv("RESEND_API_KEY")

            resend.Emails.send(
                {
                    "from": "D1 System <notifications@d1wan.org>",
                    "to": [user.email],
                    "subject": "رمز إعادة تعيين كلمة المرور - D1",
                    "html": (
                        "<div dir='rtl' style='font-family: sans-serif; padding: 20px;'>"
                        "<h2 style='color: #00A89B;'>D1 System</h2>"
                        "<p>مرحباً،</p>"
                        "<p>رمز إعادة تعيين كلمة المرور الخاص بك:</p>"
                        f"<div style='font-size: 32px; font-weight: bold; letter-spacing: 8px; "
                        f"color: #00A89B; padding: 16px; background: #f0fdf9; "
                        f"border-radius: 12px; text-align: center; margin: 16px 0;'>{otp}</div>"
                        "<p>هذا الرمز صالح لمدة <b>10 دقائق</b> فقط.</p>"
                        "<p style='color: #888; font-size: 12px;'>إذا لم تطلب إعادة تعيين كلمة المرور، تجاهل هذا البريد.</p>"
                        "</div>"
                    ),
                }
            )
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to send reset email: {str(e)}")
            # لا نكشف الخطأ للواجهة الخارجية لأسباب أمنية، لكن نسجله في logs

    return {"message": "If this email is registered, a reset code has been sent."}


@router.post("/verify-reset")
def verify_reset(data: PasswordResetVerify, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.strip().lower()).first()
    if not user or not user.reset_code or user.reset_code != data.otp:
        raise HTTPException(status_code=400, detail="INVALID_CODE")

    if not user.otp_expires_at or user.otp_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="CODE_EXPIRED")

    user.hashed_password = hash_password(data.new_password)
    user.reset_code = None
    user.otp_expires_at = None
    db.commit()
    return {"message": "Password reset successful."}