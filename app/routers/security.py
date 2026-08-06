from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
from app.models.models import User
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/security", tags=["Security"])

class SecurityLogRequest(BaseModel):
    user_id: int
    violation_type: str
    timestamp: str

@router.post("/log")
def log_security_violation(
    data: SecurityLogRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Log security violation attempts (screenshots, devtools, etc)"""
    # In production, save to a security_logs table
    # For now, just log to console
    print(f"🔒 SECURITY VIOLATION: User {current_user.email} - Type: {data.violation_type} - Time: {data.timestamp}")
    return {"logged": True}
