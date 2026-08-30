from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Notification, Issue, StatusEnum, TypeEnum, NotificationTypeEnum, User
from app.schemas import NotificationOut
from app.auth import get_current_user, require_admin
from datetime import datetime, timedelta
import os

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("")
def get_notifications(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Notification).filter(Notification.user_id == current_user.id).order_by(Notification.created_at.desc()).limit(10).all()

@router.get("/unread-count")
def get_unread_count(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    count = db.query(Notification).filter(Notification.is_read == 0).count()
    return {"count": count}

@router.patch("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if notif:
        notif.is_read = 1
        db.commit()
    return {"ok": True}

@router.patch("/read-all")
def mark_all_read(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(Notification).filter(
         Notification.user_id == current_user.id,Notification.is_read == 0).update({"is_read": 1})
    db.commit()
    return {"ok": True}

@router.delete("/{notification_id}")
def delete_notification(notification_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if notif:
        db.delete(notif)
        db.commit()
    return {"ok": True}

@router.post("/generate-smart-alerts")
def generate_smart_alerts():
    return {"message": "AI Alerts disabled temporarily"}
