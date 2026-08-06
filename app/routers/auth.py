from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import User, RoleEnum, UserStatusEnum
from app.schemas import UserCreate, UserOut, Token
from app.auth import hash_password, verify_password, create_token, get_current_user
from pydantic import BaseModel
import json, os, uuid
from datetime import datetime
import resend
from dotenv import load_dotenv

load_dotenv()

def send_verification_email_real(email_to: str, code: str):
    import resend
    
    # Reload the environment to ensure the key is captured
    from dotenv import load_dotenv
    load_dotenv()
    
    resend.api_key = os.getenv("RESEND_API_KEY", "")
    
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
        <h2>مرحباً بك في نظام إدارة المصنع</h2>
        <p>رمز التحقق الخاص بك هو:</p>
        <h1 style="color: #6a0dad; letter-spacing: 5px;">{code}</h1>
        <p>لا تشارك هذا الرمز مع أحد.</p>
    </div>
    """
    try:
        if not resend.api_key:
            print("⚠️ RESEND_API_KEY is missing! Printing code to console instead:")
            print(f"🔑 CODE for {email_to}: {code}")
            return
            
        resend.Emails.send({
            "from": "Acme Factory <onboarding@resend.dev>",
            "to": email_to,
            "subject": "رمز التحقق - نظام مصنعك",
            "html": html
        })
        print(f"✅ Fast API Email sent to {email_to}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

def send_reset_email_real(email_to: str, code: str):
    import resend
    from dotenv import load_dotenv
    load_dotenv()
    
    resend.api_key = os.getenv("RESEND_API_KEY", "")
    
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
        <h2>استعادة كلمة المرور</h2>
        <p>رمز استعادة كلمة المرور الخاص بك هو:</p>
        <h1 style="color: #d9534f; letter-spacing: 5px;">{code}</h1>
    </div>
    """
    try:
        if not resend.api_key:
            print("⚠️ RESEND_API_KEY is missing! Printing code to console instead:")
            print(f"🔑 RESET CODE for {email_to}: {code}")
            return
            
        resend.Emails.send({
            "from": "Acme Factory <onboarding@resend.dev>",
            "to": email_to,
            "subject": "استعادة كلمة المرور",
            "html": html
        })
        print(f"✅ Fast API Reset Email sent to {email_to}")
    except Exception as e:
        print(f"❌ Failed to send reset email: {e}")

router = APIRouter(prefix="/auth", tags=["Auth"])

# Mock email sender until SMTP is configured
def send_reset_email(email: str, code: str):
    print("\n" + "="*40)
    print(f"📧 EMAIL SENT TO: {email}")
    print(f"🔑 RESET CODE: {code}")
    print("="*40 + "\n")

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str

class VerifyEmailRequest(BaseModel):
    email: str
    code: str

def send_verification_email(email: str, code: str):
    print("\n" + "="*40)
    print(f"📧 VERIFICATION EMAIL SENT TO: {email}")
    print(f"🔑 VERIFICATION CODE: {code}")
    print("="*40 + "\n")

# In-memory store for pending registrations (code -> user data)
pending_registrations = {}

@router.post("/register")
def register(data: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Check if email already exists in database
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Check if this email already has a pending verification
    for code, pending in pending_registrations.items():
        if pending["email"] == data.email:
            # Resend code for existing pending registration
            background_tasks.add_task(send_verification_email_real, data.email, code)
            return {"message": "Verification code sent to email"}
    
    verify_code = str(uuid.uuid4()).split('-')[0].upper()
    
    # Store in memory, NOT in database yet
    pending_registrations[verify_code] = {
        "name": data.name,
        "email": data.email,
        "password": hash_password(data.password),
        "created_at": datetime.utcnow()
    }
    
    # Print code to backend terminal AND try to send email
    print("\n" + "="*45)
    print(f"📧 EMAIL TO: {data.email}")
    print(f"🔑 VERIFICATION CODE: {verify_code}")
    print("="*45 + "\n")
    
    try:
        background_tasks.add_task(send_verification_email_real, data.email, verify_code)
    except:
        pass
    
    return {"message": "Verification code sent to email"}

@router.post("/verify-email")
def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    code = data.code.strip().upper()
    
    if code not in pending_registrations:
        raise HTTPException(status_code=400, detail="Invalid verification code")
    
    pending = pending_registrations[code]
    
    # Create the actual user now
    user = User(
        name=pending["name"],
        email=pending["email"],
        hashed_password=pending["password"],
        status=UserStatusEnum.pending,
        permissions=json.dumps({"can_add": True, "can_delete": False, "can_edit_permissions": False})
    )
    db.add(user)
    db.commit()
    
    # Remove from pending
    del pending_registrations[code]
    
    return {"message": "Email verified successfully. Account created pending admin approval."}

@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form.username.strip().lower()
    user = db.query(User).filter(User.email.ilike(email)).first()
    
    print("\n--- LOGIN DEBUG ---")
    print(f"Trying to login: {email}")
    if not user:
        print("Result: USER NOT FOUND IN DB")
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    print(f"User found: ID={user.id}, Status={user.status.value}, Email={user.email}")
    
    if not verify_password(form.password, user.hashed_password):
        print("Result: WRONG PASSWORD")
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    if user.status == UserStatusEnum.unverified:
        print("Result: BLOCKED (UNVERIFIED)")
        raise HTTPException(status_code=403, detail="UNVERIFIED")
    if user.status == UserStatusEnum.pending:
        print("Result: BLOCKED (PENDING)")
        raise HTTPException(status_code=403, detail="PENDING")
    if user.status == UserStatusEnum.rejected:
        print("Result: BLOCKED (REJECTED)")
        raise HTTPException(status_code=403, detail="REJECTED")
        
    print("Result: LOGIN SUCCESS")
    print("-------------------\n")
    
    token = create_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        return {"message": "If the email exists, a reset code has been sent."}
    
    code = str(uuid.uuid4()).split('-')[0].upper()
    user.reset_code = code
    db.commit()
    
    background_tasks.add_task(send_reset_email_real, user.email, code)
    return {"message": "If the email exists, a reset code has been sent."}

@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or user.reset_code != data.code:
        raise HTTPException(status_code=400, detail="Invalid code or email")
    
    user.hashed_password = hash_password(data.new_password)
    user.reset_code = None
    
    # Auto-approve if they reset password successfully to get them back in
    if user.status != UserStatusEnum.approved:
        user.status = UserStatusEnum.approved
        
    db.commit()
    return {"message": "Password updated successfully"}

@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
