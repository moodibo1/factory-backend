from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.models.models import Issue, MonthlyReport, StatusEnum
from app.reporting import REPORTS_DIR, generate_report_pdf

logger = logging.getLogger(__name__)
VALID_DEPARTMENTS = ("lab", "secondary_packaging", "production")

# ---------------------------------------------------------------------------
# Storage configuration helpers
# ---------------------------------------------------------------------------
STORAGE_QUOTA_BYTES = 1_073_741_824  # 1 GB Supabase free-tier
EMERGENCY_THRESHOLD = 0.85           # 85 % triggers circuit breaker
EMERGENCY_RECLAIM_TARGET = 0.50      # reclaim down to ~50 %


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        return start, datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return start, datetime(year, month + 1, 1, tzinfo=timezone.utc)


def _bimonth_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return (start, end) spanning a 2-month window ending at *month*."""
    if month <= 1:
        start_year, start_month = year - 1, month + 11
    else:
        start_year, start_month = year, month - 1
    start = datetime(start_year, start_month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _storage_object_path(media_url: str | None, bucket_name: str) -> str | None:
    if not media_url:
        return None
    parsed = urlparse(media_url)
    parts = [part for part in parsed.path.split("/") if part]
    try:
        bucket_index = parts.index(bucket_name)
    except ValueError:
        return None
    object_parts = parts[bucket_index + 1:]
    return "/".join(object_parts) or None


def _supabase_config() -> tuple[str, str, str]:
    """Return (supabase_url, service_key, bucket_name) or raise."""
    supabase_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    bucket_name = os.getenv("SUPABASE_BUCKET", "media")
    if not supabase_url or not service_key:
        raise RuntimeError("Supabase storage configuration is missing")
    return supabase_url, service_key, bucket_name


def _delete_storage_object(media_url: str | None) -> None:
    """Delete a single object from Supabase Storage. Idempotent on 404."""
    if not media_url:
        return
    supabase_url, service_key, bucket_name = _supabase_config()
    object_path = _storage_object_path(media_url, bucket_name)

    # Try legacy bucket if primary doesn't match
    if object_path is None:
        legacy_bucket = os.getenv("SUPABASE_ISSUES_BUCKET", "issues")
        object_path = _storage_object_path(media_url, legacy_bucket)
        if object_path is not None:
            bucket_name = legacy_bucket

    if not object_path:
        logger.warning("Cannot resolve storage path from URL: %s", media_url)
        return

    response = requests.delete(
        f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket_name}/{object_path}",
        headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
        timeout=30,
    )
    # 404 = already gone, that's fine
    if response.status_code >= 400 and response.status_code != 404:
        raise RuntimeError(
            f"Storage deletion failed ({response.status_code}): {response.text[:300]}"
        )


# ---------------------------------------------------------------------------
# Storage usage estimation
# ---------------------------------------------------------------------------

def estimate_storage_usage(db: Session) -> dict:
    """Estimate total Supabase storage usage from DB media_url records.

    This avoids needing Supabase list-all API (which can be slow/paginated).
    We count issues with media, estimate average size, and return metrics.
    """
    supabase_url, service_key, bucket_name = _supabase_config()

    # Try to get real usage via Supabase list API (top-level)
    total_bytes = 0
    file_count = 0
    try:
        list_url = f"{supabase_url.rstrip('/')}/storage/v1/object/list/{bucket_name}"
        response = requests.post(
            list_url,
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
                "Content-Type": "application/json",
            },
            json={"limit": 10000, "offset": 0},
            timeout=30,
        )
        if response.status_code < 400:
            objects = response.json()
            if isinstance(objects, list):
                for obj in objects:
                    if isinstance(obj, dict) and obj.get("metadata"):
                        size = obj["metadata"].get("size", 0)
                        total_bytes += int(size) if size else 0
                        file_count += 1
                    elif isinstance(obj, dict) and obj.get("name"):
                        file_count += 1
    except Exception as exc:
        logger.warning("Failed to list Supabase storage objects: %s", exc)

    # Fallback: estimate from DB if API gave nothing useful
    if total_bytes == 0 and file_count == 0:
        media_count = (
            db.query(Issue)
            .filter(Issue.media_url.is_not(None), Issue.is_archived.is_(False))
            .count()
        )
        # Conservative estimate: 300KB average per compressed image
        avg_size = 300 * 1024
        total_bytes = media_count * avg_size
        file_count = media_count

    usage_pct = (total_bytes / STORAGE_QUOTA_BYTES) * 100 if STORAGE_QUOTA_BYTES else 0

    return {
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "file_count": file_count,
        "quota_bytes": STORAGE_QUOTA_BYTES,
        "quota_mb": round(STORAGE_QUOTA_BYTES / (1024 * 1024), 2),
        "usage_percent": round(usage_pct, 2),
        "threshold_percent": round(EMERGENCY_THRESHOLD * 100, 2),
        "above_threshold": usage_pct >= (EMERGENCY_THRESHOLD * 100),
    }


# ---------------------------------------------------------------------------
# Bi-monthly dossier generation
# ---------------------------------------------------------------------------

def _upsert_monthly_report(
    db: Session,
    department: str,
    year: int,
    month: int,
    issues: list[Issue],
    pdf_path: str,
) -> MonthlyReport:
    report = (
        db.query(MonthlyReport)
        .filter(
            MonthlyReport.department == department,
            MonthlyReport.year == year,
            MonthlyReport.month == month,
        )
        .one_or_none()
    )
    if report is None:
        report = MonthlyReport(department=department, year=year, month=month)
        db.add(report)
    report.title = f"Bi-monthly report — {department} — {year}-{month:02d}"
    report.total_issues = len(issues)
    report.open_issues = sum(issue.status == StatusEnum.open for issue in issues)
    report.closed_issues = sum(issue.status == StatusEnum.closed for issue in issues)
    report.file_path = str(Path(pdf_path).resolve())
    report.file_url = f"/uploads/reports/{Path(pdf_path).name}"
    return report


def run_bimonthly_cycle(target_year: int, target_month: int, db: Session) -> dict:
    """Task A + Task B: generate dossiers for all departments, then purge old images."""
    if not 1 <= target_month <= 12:
        raise ValueError("target_month must be between 1 and 12")
    if not 2000 <= target_year <= 9999:
        raise ValueError("target_year is out of range")

    # ── Task A: Generate bi-monthly PDF dossiers ──────────────────────────
    start_dt, end_dt = _bimonth_bounds(target_year, target_month)
    generated: list[MonthlyReport] = []

    try:
        for department in VALID_DEPARTMENTS:
            issues = (
                db.query(Issue)
                .filter(
                    Issue.category == department,
                    Issue.created_at >= start_dt,
                    Issue.created_at < end_dt,
                )
                .order_by(Issue.created_at.desc())
                .all()
            )
            title = f"Bi-monthly report — {department} — {target_year}-{target_month:02d}"
            pdf_path = generate_report_pdf(
                title=title,
                department=department,
                issues=issues,
                language="ar",
                start_date=start_dt.strftime("%Y-%m-%d"),
                end_date=(end_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                output_dir=str(REPORTS_DIR),
            )
            if not Path(pdf_path).is_file() or Path(pdf_path).stat().st_size < 1000:
                raise RuntimeError(f"Generated report is invalid: {pdf_path}")
            generated.append(
                _upsert_monthly_report(db, department, target_year, target_month, issues, pdf_path)
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Bi-monthly report generation failed %04d-%02d", target_year, target_month)
        raise

    # ── Task B: Purge closed-issue images older than prior month ───────────
    retention_cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    purged = 0
    failed_ids: list[int] = []

    try:
        closed_issues = (
            db.query(Issue)
            .filter(
                Issue.status == StatusEnum.closed,
                Issue.is_archived.is_(False),
                Issue.closed_at.is_not(None),
                Issue.closed_at < retention_cutoff,
                Issue.media_url.is_not(None),
            )
            .order_by(Issue.closed_at.asc())
            .all()
        )
        for issue in closed_issues:
            try:
                _delete_storage_object(issue.media_url)
                issue.media_url = None
                issue.media_type = None
                issue.is_archived = True
                purged += 1
            except Exception:
                failed_ids.append(issue.id)
                logger.exception("Failed to purge image for issue %s", issue.id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Bi-monthly storage purge failed")
        raise

    logger.info(
        "Bi-monthly cycle completed %04d-%02d: %d reports, %d images purged, %d failed",
        target_year, target_month, len(generated), purged, len(failed_ids),
    )
    return {
        "year": target_year,
        "month": target_month,
        "reports": generated,
        "purged_count": purged,
        "failed_issue_ids": failed_ids,
        "retention_cutoff": retention_cutoff.isoformat(),
    }


# ---------------------------------------------------------------------------
# Emergency fallback (Circuit Breaker)
# ---------------------------------------------------------------------------

def run_emergency_fallback(db: Session, reason: str = "manual") -> dict:
    """FIFO purge of closed-issue images to reclaim ~50% of storage.

    Targets ONLY closed issues, oldest first.
    For each purged image: media_url → None, is_archived → True,
    and a log note is appended.
    """
    usage = estimate_storage_usage(db)
    target_bytes = int(STORAGE_QUOTA_BYTES * EMERGENCY_RECLAIM_TARGET)
    bytes_to_free = max(0, usage["total_bytes"] - target_bytes)

    if bytes_to_free <= 0:
        logger.info("Emergency fallback: no reclamation needed (%.1f%% used)", usage["usage_percent"])
        return {
            "triggered": False,
            "reason": reason,
            "usage_before": usage,
            "purged_count": 0,
            "failed_issue_ids": [],
        }

    # Estimate average file size for calculating how many to delete
    avg_file_bytes = max(
        (usage["total_bytes"] // usage["file_count"]) if usage["file_count"] > 0 else 300 * 1024,
        50 * 1024,  # floor at 50KB
    )
    estimated_files_to_delete = (bytes_to_free // avg_file_bytes) + 1

    closed_issues = (
        db.query(Issue)
        .filter(
            Issue.status == StatusEnum.closed,
            Issue.is_archived.is_(False),
            Issue.media_url.is_not(None),
            Issue.closed_at.is_not(None),
        )
        .order_by(Issue.closed_at.asc())  # FIFO: oldest closed first
        .limit(int(estimated_files_to_delete * 1.2))  # 20% buffer
        .all()
    )

    purged = 0
    failed_ids: list[int] = []
    bytes_freed_estimate = 0

    try:
        for issue in closed_issues:
            if bytes_freed_estimate >= bytes_to_free:
                break
            try:
                _delete_storage_object(issue.media_url)
                # Only update DB after confirmed Supabase deletion
                issue.media_url = None
                issue.media_type = None
                issue.is_archived = True
                purged += 1
                bytes_freed_estimate += avg_file_bytes
            except Exception:
                failed_ids.append(issue.id)
                logger.exception("Emergency fallback: failed to purge issue %s", issue.id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Emergency fallback commit failed")
        raise

    logger.warning(
        "[Emergency Storage Fallback: Media purged to reclaim capacity] "
        "reason=%s, purged=%d, estimated_freed=%.1f MB, failed=%d",
        reason, purged, bytes_freed_estimate / (1024 * 1024), len(failed_ids),
    )

    return {
        "triggered": True,
        "reason": reason,
        "usage_before": usage,
        "purged_count": purged,
        "estimated_freed_mb": round(bytes_freed_estimate / (1024 * 1024), 2),
        "failed_issue_ids": failed_ids,
    }


# ---------------------------------------------------------------------------
# Standalone entry for run_monthly_archival_and_cleanup (backward compat)
# ---------------------------------------------------------------------------

def run_monthly_archival_and_cleanup(target_year: int, target_month: int) -> dict:
    """Backward-compatible wrapper with its own session."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        return run_bimonthly_cycle(target_year, target_month, db)
    finally:
        db.close()


def _run_monthly_archival_and_cleanup(
    target_year: int,
    target_month: int,
    db: Session,
    retention_days: int = 60,
) -> dict:
    """Backward-compatible wrapper delegating to run_bimonthly_cycle."""
    return run_bimonthly_cycle(target_year, target_month, db)
