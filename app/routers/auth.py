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


from dotenv import load_dotenv



load_dotenv()



import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def get_smtp_config():
    return {
        "server": os.getenv("SMTP_SERVER", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", 587)),
        "username": os.getenv("SMTP_USERNAME", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_email": os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USERNAME", ""))
    }

def send_smtp_email(to_email: str, subject: str, html_content: str):
    config = get_smtp_config()
    
    if not config["username"] or not config["password"]:
        print(f"⚠️ SMTP credentials missing! Skipping email to {to_email}. CONTENT:\n{html_content}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["from_email"]
    msg["To"] = to_email

    part = MIMEText(html_content, "html")
    msg.attach(part)

    try:
        server = smtplib.SMTP(config["server"], config["port"])
        server.starttls()
        server.login(config["username"], config["password"])
        server.sendmail(config["from_email"], to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"❌ Failed to send SMTP email: {e}")
        return False

def send_verification_email_real(email_to: str, code: str):
    from dotenv import load_dotenv
    load_dotenv()
    
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
        <h2>رسالة تحقق من نظام المصنع</h2>
        <p>رمز الدخول الخاص بك هو:</p>
        <h1 style="color: #6a0dad; letter-spacing: 5px;">{code}</h1>
        <p>يرجى إدخاله في النظام لإكمال التسجيل.</p>
    </div>
    """
    success = send_smtp_email(email_to, "رسالة التحقق - نظام المصنع", html)
    if success:
        print(f"📧 Fast API Email sent via SMTP to {email_to}")

def send_reset_email_real(email_to: str, code: str):
    from dotenv import load_dotenv
    load_dotenv()
    
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
        <h2>استعادة كلمة المرور</h2>
        <p>رمز استعادة كلمة المرور الخاص بك هو:</p>
        <h1 style="color: ##eab308; letter-spacing: 5px;">{code}</h1>
        <p>إذا لم تطلب هذا، يمكنك تجاهل هذه الرسالة.</p>
    </div>
    """
    success = send_smtp_email(email_to, "استعادة كلمة المرور", html)
    if success:
        print(f"📧 Fast API Reset Email sent via SMTP to {email_to}")

router = APIRouter(prefix="/auth", tags=["Auth"])



# Mock email sender until SMTP is configured

def send_reset_email(email: str, code: str):

    print("\n" + "="*40)

    print(f"ðŸ“§ EMAIL SENT TO: {email}")

    print(f"ðŸ”‘ RESET CODE: {code}")

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

    print(f"ðŸ“§ VERIFICATION EMAIL SENT TO: {email}")

    print(f"ðŸ”‘ VERIFICATION CODE: {code}")

    print("="*40 + "\n")



# In-memory store for pending registrations (code -> user data)





@router.post("/register")
def register(data: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    from datetime import datetime, timedelta
    import uuid
    import json
    existing_user = db.query(User).filter(User.email == data.email).first()
    
    verify_code = str(uuid.uuid4()).split('-')[0].upper()
    expires_at = datetime.utcnow() + timedelta(minutes=15)
    
    if existing_user:
        if getattr(existing_user, 'is_verified', False):
            raise HTTPException(status_code=400, detail="Email already registered and verified")
        else:
            existing_user.verification_code = verify_code
            existing_user.token_expires_at = expires_at
            db.commit()
    else:
        new_user = User(
            name=data.name,
            email=data.email,
            hashed_password=hash_password(data.password),
            status=UserStatusEnum.pending,
            is_verified=False,
            verification_code=verify_code,
            token_expires_at=expires_at,
            permissions=json.dumps({"can_add": True, "can_delete": False, "can_edit_permissions": False})
        )
        db.add(new_user)
        db.commit()

    print("\n" + "="*45)
    print(f"EMAIL TO: {data.email}")
    print(f"VERIFICATION CODE: {verify_code}")
    print("="*45 + "\n")
    try:
        background_tasks.add_task(send_verification_email_real, data.email, verify_code)
    except:
        pass
        
    return {"message": "Verification code sent to email"}

@router.post("/verify-email")
def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    from datetime import datetime
    code = data.code.strip().upper()
    user = db.query(User).filter(User.email == data.email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if getattr(user, 'is_verified', False):
        return {"message": "User is already verified"}
        
    if user.verification_code != code:
        raise HTTPException(status_code=400, detail="Invalid verification code")
        
    if getattr(user, "token_expires_at", None) and user.token_expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Verification code expired")

    user.is_verified = True
    user.verification_code = None
    user.token_expires_at = None
    db.commit()

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
    if getattr(user, 'is_verified', False) is False:
        print("Result: BLOCKED (NOT VERIFIED)")
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")


    

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

