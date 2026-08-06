from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Issue, TypeEnum, StatusEnum
from app.schemas import DashboardStats
from app.auth import require_admin
from app.models.models import User
import csv
import os
from io import StringIO
from fastapi.responses import StreamingResponse
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    issues = db.query(Issue).all()
    return {
        "total": len(issues),
        "open": sum(1 for i in issues if i.status == StatusEnum.open),
        "closed": sum(1 for i in issues if i.status == StatusEnum.closed),
        "emergency": sum(1 for i in issues if i.type == TypeEnum.emergency),
        "by_category": {
            "lab": sum(1 for i in issues if i.category == "lab"),
            "filling": sum(1 for i in issues if i.category == "filling"),
            "production": sum(1 for i in issues if i.category == "production"),
        },
    }

@router.get("/export")
def export_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    q = db.query(Issue)
    
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            q = q.filter(Issue.created_at >= start_dt)
        except ValueError:
            pass
            
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            q = q.filter(Issue.created_at < end_dt)
        except ValueError:
            pass

    issues = q.order_by(Issue.created_at.desc()).all()
    output = StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["الرقم", "العنوان", "الوصف", "القسم", "النوع", "الحالة", "الكاتب", "تاريخ الإنشاء", "تاريخ الإغلاق"])
    category_map = {"lab": "المختبرات", "filling": "التعبئة", "production": "الإنتاج"}
    type_map = {"problem": "مشكلة", "note": "ملاحظة", "emergency": "أمر طارئ"}
    status_map = {"open": "مفتوح", "in_progress": "قيد المعالجة", "closed": "مغلق", "reopened": "معاد فتحه"}
    for i in issues:
        writer.writerow([
            i.id, i.title, i.description or "",
            category_map.get(i.category, i.category),
            type_map.get(i.type, i.type),
            status_map.get(i.status, i.status),
            i.creator.name if i.creator else "مجهول",
            i.created_at.strftime("%Y-%m-%d %H:%M") if i.created_at else "",
            i.closed_at.strftime("%Y-%m-%d %H:%M") if i.closed_at else ""
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=Factory_Issues_Report.csv"}
    )

@router.get("/ai-report")
async def ai_report(custom_prompt: Optional[str] = None, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    # AI Report temporarily disabled
    return {"report": "تقرير الذكاء الاصطناعي معطل مؤقتاً. الخدمة ستعود قريباً."}
