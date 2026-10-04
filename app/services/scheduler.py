from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.models import Issue, MonthlyReport, StatusEnum
from app.reporting import REPORTS_DIR, generate_report_pdf

logger = logging.getLogger(__name__)

VALID_DEPARTMENTS = ("lab", "secondary_packaging", "production")
RETENTION_DAYS = 60

# Advisory lock IDs — arbitrary unique integers per job type
_LOCK_BIMONTHLY = 900_001
_LOCK_DAILY_CHECK = 900_002

_scheduler: BackgroundScheduler | None = None


# ---------------------------------------------------------------------------
# PostgreSQL advisory lock guard
# ---------------------------------------------------------------------------

def _try_advisory_lock(db: Session, lock_id: int) -> bool:
    """Attempt a session-level advisory lock. Returns True if acquired."""
    result = db.execute(text(f"SELECT pg_try_advisory_lock({lock_id})"))
    return result.scalar() is True


def _release_advisory_lock(db: Session, lock_id: int) -> None:
    """Release a session-level advisory lock."""
    db.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))


# ---------------------------------------------------------------------------
# Helpers (kept for backward compatibility with existing report jobs)
# ---------------------------------------------------------------------------

def _previous_bimonth(now: datetime) -> tuple[int, int]:
    """Return (year, month) of the month that just ended."""
    first_of_current_month = now.replace(day=1)
    previous_month = first_of_current_month - timedelta(days=1)
    return previous_month.year, previous_month.month


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        return start, datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return start, datetime(year, month + 1, 1, tzinfo=timezone.utc)


def _storage_object_path(media_url: str, bucket_name: str) -> tuple[str, str] | None:
    parsed = urlparse(media_url)
    parts = [part for part in parsed.path.split("/") if part]
    try:
        bucket_index = parts.index(bucket_name)
    except ValueError:
        return None
    object_path = "/".join(parts[bucket_index + 1:])
    return (bucket_name, object_path) if object_path else None


def _delete_issue_image(media_url: str) -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    configured_bucket = os.getenv("SUPABASE_ISSUES_BUCKET", "issues")
    if not supabase_url or not service_key:
        raise RuntimeError("Supabase storage configuration is missing")

    storage_object = _storage_object_path(media_url, configured_bucket)
    if storage_object is None:
        legacy_bucket = os.getenv("SUPABASE_BUCKET", "media")
        storage_object = _storage_object_path(media_url, legacy_bucket)
        if storage_object is None:
            raise RuntimeError(f"Unable to resolve Supabase object path from media URL: {media_url}")

    bucket_name, object_path = storage_object
    response = requests.delete(
        f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket_name}/{object_path}",
        headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
        timeout=30,
    )
    if response.status_code >= 400 and response.status_code != 404:
        raise RuntimeError(
            f"Supabase image deletion failed ({response.status_code}): {response.text[:300]}"
        )


def _upsert_report(
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


# ---------------------------------------------------------------------------
# JOB 1: Bi-monthly dossier generation + image purge
# ---------------------------------------------------------------------------

def generate_bimonthly_reports_job() -> dict:
    """Generate & persist the previous period's departmental dossiers,
    then purge closed-issue images older than RETENTION_DAYS.

    Guarded by advisory lock to prevent duplicate execution across workers.
    """
    db = SessionLocal()
    try:
        if not _try_advisory_lock(db, _LOCK_BIMONTHLY):
            logger.info("Bi-monthly job skipped — another worker holds the lock")
            return {"skipped": True, "reason": "advisory_lock_held"}

        try:
            from app.maintenance import run_bimonthly_cycle
            now = datetime.now(timezone.utc)
            target_year, target_month = _previous_bimonth(now)
            return run_bimonthly_cycle(target_year, target_month, db)
        finally:
            _release_advisory_lock(db, _LOCK_BIMONTHLY)
    except Exception:
        logger.exception("Bi-monthly cycle job failed")
        raise
    finally:
        db.close()


# Keep old name as alias for backward compatibility
generate_monthly_reports_job = generate_bimonthly_reports_job


# ---------------------------------------------------------------------------
# JOB 2: Image purge (standalone, kept for backward compat)
# ---------------------------------------------------------------------------

def purge_two_month_old_images_job() -> dict:
    """Delete old closed-issue images while preserving every issue row."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    db = SessionLocal()
    purged = 0
    failed: list[int] = []
    try:
        issues = (
            db.query(Issue)
            .filter(
                Issue.status == StatusEnum.closed,
                Issue.closed_at.is_not(None),
                Issue.closed_at < cutoff,
                Issue.media_url.is_not(None),
                Issue.is_archived.is_(False),
            )
            .all()
        )
        for issue in issues:
            try:
                _delete_issue_image(issue.media_url)
                issue.media_url = None
                issue.media_type = None
                issue.is_archived = True
                purged += 1
            except Exception:
                failed.append(issue.id)
                logger.exception("Failed to purge image for issue %s", issue.id)
        db.commit()
        logger.info(
            "Purged %d closed-issue images older than %d days; %d failed",
            purged, RETENTION_DAYS, len(failed),
        )
        return {
            "cutoff": cutoff.isoformat(),
            "purged_count": purged,
            "failed_issue_ids": failed,
        }
    except Exception:
        db.rollback()
        logger.exception("Closed-issue image purge failed")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# JOB 3: Daily storage circuit breaker check
# ---------------------------------------------------------------------------

def daily_storage_check_job() -> dict:
    """Daily check: if storage exceeds 85%, trigger emergency fallback."""
    db = SessionLocal()
    try:
        if not _try_advisory_lock(db, _LOCK_DAILY_CHECK):
            logger.info("Daily storage check skipped — another worker holds the lock")
            return {"skipped": True, "reason": "advisory_lock_held"}

        try:
            from app.maintenance import estimate_storage_usage, run_emergency_fallback, EMERGENCY_THRESHOLD
            usage = estimate_storage_usage(db)
            logger.info(
                "Daily storage check: %.1f%% used (%.1f MB / %.1f MB)",
                usage["usage_percent"], usage["total_mb"], usage["quota_mb"],
            )

            if usage["above_threshold"]:
                logger.warning(
                    "Storage above %.0f%% threshold (%.1f%%) — triggering emergency fallback",
                    EMERGENCY_THRESHOLD * 100, usage["usage_percent"],
                )
                return run_emergency_fallback(db, reason="daily_circuit_breaker")

            return {
                "triggered": False,
                "usage": usage,
                "message": "Storage within safe limits",
            }
        finally:
            _release_advisory_lock(db, _LOCK_DAILY_CHECK)
    except Exception:
        logger.exception("Daily storage check failed")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    timezone_name = os.getenv("MONTHLY_MAINTENANCE_TIMEZONE", "UTC")
    _scheduler = BackgroundScheduler(timezone=timezone_name)

    # Bi-monthly: 1st of every other month (Jan, Mar, May, Jul, Sep, Nov) at 01:00
    bimonthly_trigger = CronTrigger(
        month="1,3,5,7,9,11",
        day=1,
        hour=1,
        minute=0,
        timezone=timezone_name,
    )
    _scheduler.add_job(
        generate_bimonthly_reports_job,
        trigger=bimonthly_trigger,
        id="generate-bimonthly-reports",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=6 * 60 * 60,
    )

    # Image purge: runs 15 min after dossier generation
    purge_trigger = CronTrigger(
        month="1,3,5,7,9,11",
        day=1,
        hour=1,
        minute=15,
        timezone=timezone_name,
    )
    _scheduler.add_job(
        purge_two_month_old_images_job,
        trigger=purge_trigger,
        id="purge-closed-issue-images",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=6 * 60 * 60,
    )

    # Daily circuit breaker: every day at 03:00
    daily_trigger = CronTrigger(
        hour=3,
        minute=0,
        timezone=timezone_name,
    )
    _scheduler.add_job(
        daily_storage_check_job,
        trigger=daily_trigger,
        id="daily-storage-circuit-breaker",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=2 * 60 * 60,
    )

    _scheduler.start()
    logger.info(
        "Maintenance scheduler started: bi-monthly reports 01:00 (odd months), "
        "image purge 01:15, daily storage check 03:00 (%s)",
        timezone_name,
    )
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
