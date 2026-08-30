from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import User, UserStatusEnum
from app.schemas import UserCreate, UserOut, Token
from app.auth import get_current_user, hash_password, verify_password, create_token
import json

router = APIRouter(prefix="/auth", tags=["Auth"])

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
        permissions=json.dumps({"can_add": True, "can_delete": False, "can_edit_permissions": False})
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

    if getattr(user, 'status', None) == UserStatusEnum.pending:
        raise HTTPException(status_code=403, detail="PENDING")
    
    if getattr(user, 'status', None) == UserStatusEnum.rejected:
        raise HTTPException(status_code=403, detail="REJECTED")

    # In case there are leftover 'unverified' users from earlier code
    if getattr(user, 'status', None) == UserStatusEnum.unverified:
        raise HTTPException(status_code=403, detail="PENDING")

    token = create_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
