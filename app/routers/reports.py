from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.models import CategoryEnum, Issue, MonthlyReport, StatusEnum, User
from app.reporting import REPORTS_DIR, generate_report_pdf
from app.schemas import CustomReportRequest, MonthlyReportOut

router = APIRouter(prefix="/reports", tags=["Reports"])

VALID_DEPARTMENTS = [category.value for category in CategoryEnum if category.value in {"lab", "secondary_packaging", "production"}]


def _department_value(department: str) -> str:
    try:
        return CategoryEnum(department).value
    except ValueError:
        return department


def _pdf_response(path: str | Path, disposition: str, filename: str = "report.pdf") -> FileResponse:
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get("/monthly/{report_id}/file")
def get_monthly_report_file(
    report_id: int,
    disposition: str = Query(default="inline", pattern="^(inline|attachment)$"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    report = db.query(MonthlyReport).filter(MonthlyReport.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if not report.file_path:
        raise HTTPException(status_code=404, detail="Report file is not available")

    report_path = Path(report.file_path)
    if not report_path.is_absolute():
        report_path = (Path(__file__).resolve().parents[2] / report_path).resolve()
    else:
        report_path = report_path.resolve()

    reports_root = REPORTS_DIR.resolve()
    if not report_path.is_file():
        start_dt = datetime(report.year, report.month, 1, tzinfo=timezone.utc)
        end_dt = (
            datetime(report.year + 1, 1, 1, tzinfo=timezone.utc)
            if report.month == 12
            else datetime(report.year, report.month + 1, 1, tzinfo=timezone.utc)
        )
        issues = (
            db.query(Issue)
            .filter(Issue.category == _department_value(report.department))
            .filter(Issue.created_at >= start_dt)
            .filter(Issue.created_at < end_dt)
            .order_by(Issue.created_at.desc())
            .all()
        )
        try:
            regenerated_path = generate_report_pdf(
                title=report.title,
                department=report.department,
                issues=issues,
                language="ar",
                start_date=start_dt.strftime("%Y-%m-%d"),
                end_date=(end_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                output_dir=str(REPORTS_DIR),
            )
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="PDF generation is unavailable. Install the backend PDF dependencies.",
            ) from error
        report_path = Path(regenerated_path).resolve()
        report.file_path = str(report_path)
        report.file_url = f"/uploads/reports/{report_path.name}"
        db.commit()

    return _pdf_response(report_path, disposition, "report.pdf")


@router.get("/monthly", response_model=list[MonthlyReportOut])
def list_monthly_reports(
    department: Optional[str] = Query(default=None),
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    query = db.query(MonthlyReport)
    if department:
        query = query.filter(MonthlyReport.department == department)
    if year is not None:
        query = query.filter(MonthlyReport.year == year)
    if month is not None:
        query = query.filter(MonthlyReport.month == month)

    return query.order_by(MonthlyReport.created_at.desc()).all()


@router.post("/custom-export")
def custom_export(
    data: CustomReportRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if data.department not in VALID_DEPARTMENTS:
        raise HTTPException(status_code=400, detail=f"Invalid department. Allowed: {VALID_DEPARTMENTS}")
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after start date")

    start_dt = datetime.combine(data.start_date, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(data.end_date, time.max, tzinfo=timezone.utc)

    issues = (
        db.query(Issue)
        .filter(Issue.category == _department_value(data.department))
        .filter(Issue.created_at >= start_dt)
        .filter(Issue.created_at <= end_dt)
        .order_by(Issue.created_at.desc())
        .all()
    )

    title = f"{data.department} - {data.start_date.isoformat()} to {data.end_date.isoformat()}"
    try:
        output_path = generate_report_pdf(
            title=title,
            department=data.department,
            issues=issues,
            language=data.language,
            start_date=data.start_date.isoformat(),
            end_date=data.end_date.isoformat(),
            output_dir=str(REPORTS_DIR),
        )
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail="PDF generation is unavailable. Install the backend PDF dependencies.",
        ) from error
    filename = f"report_{data.department}_{data.start_date.isoformat()}_{data.end_date.isoformat()}.pdf"
    return _pdf_response(output_path, "inline", filename)


@router.post("/generate-monthly-batch", response_model=list[MonthlyReportOut])
def generate_monthly_batch(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    now = datetime.utcnow()
    target_year = year or now.year
    target_month = month or now.month

    generated: list[MonthlyReport] = []
    for department in VALID_DEPARTMENTS:
        start_dt = datetime(target_year, target_month, 1, tzinfo=timezone.utc)
        if target_month == 12:
            end_dt = datetime(target_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end_dt = datetime(target_year, target_month + 1, 1, tzinfo=timezone.utc)

        issues = (
            db.query(Issue)
            .filter(Issue.category == _department_value(department))
            .filter(Issue.created_at >= start_dt)
            .filter(Issue.created_at < end_dt)
            .all()
        )

        open_count = sum(1 for issue in issues if issue.status == StatusEnum.open)
        closed_count = sum(1 for issue in issues if issue.status == StatusEnum.closed)

        existing = (
            db.query(MonthlyReport)
            .filter(MonthlyReport.department == department)
            .filter(MonthlyReport.month == target_month)
            .filter(MonthlyReport.year == target_year)
            .first()
        )

        report = existing or MonthlyReport(
            title=f"Monthly report - {department} - {target_year}-{target_month:02d}",
            department=department,
            month=target_month,
            year=target_year,
            total_issues=0,
            open_issues=0,
            closed_issues=0,
        )

        report.title = f"Monthly report - {department} - {target_year}-{target_month:02d}"
        report.department = department
        report.month = target_month
        report.year = target_year
        report.total_issues = len(issues)
        report.open_issues = open_count
        report.closed_issues = closed_count

        try:
            pdf_path = generate_report_pdf(
                title=report.title,
                department=department,
                issues=issues,
                language="ar",
                start_date=start_dt.strftime("%Y-%m-%d"),
                end_date=(end_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                output_dir=str(REPORTS_DIR),
            )
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="PDF generation is unavailable. Install the backend PDF dependencies.",
            ) from error
        relative_name = pdf_path.replace('\\', '/').split('uploads/')[-1] if 'uploads/' in pdf_path.replace('\\', '/') else pdf_path.split('/')[-1]
        report.file_path = pdf_path
        report.file_url = f"/uploads/{relative_name}"

        if existing is None:
            db.add(report)
        db.flush()
        generated.append(report)

    db.commit()
    for report in generated:
        db.refresh(report)
    return generated
