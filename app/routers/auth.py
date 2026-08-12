from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models.models import User, UserStatusEnum
from app.schemas import UserOut
from app.auth import get_current_user
import json

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: str
    name: str


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Called by the frontend /auth/callback page after Supabase confirms the user's email.
    Creates the Postgres user row as 'pending' for admin approval.
    Idempotent: safe to call more than once for the same email.
    """
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        return {"message": "Account already exists. Awaiting admin approval."}

    new_user = User(
        name=data.name,
        email=data.email,
        hashed_password="supabase-managed",
        status=UserStatusEnum.pending,
        permissions=json.dumps({"can_add": True, "can_delete": False, "can_edit_permissions": False})
    )
    db.add(new_user)
    db.commit()
    return {"message": "Registration successful. Awaiting admin approval."}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
