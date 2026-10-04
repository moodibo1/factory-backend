from __future__ import annotations

import base64
import html
import logging
import mimetypes
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.models.models import Issue
from app.services.pdf_engine import generate_pdf_from_html

logger = logging.getLogger(__name__)

BASE_UPLOADS_DIR = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads")))
REPORTS_DIR = BASE_UPLOADS_DIR / "reports"
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "report_template.html"
FONT_DIR = Path(__file__).resolve().parent / "fonts"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

LABELS = {
    "ar": {
        "period": "الفترة", "generated": "تاريخ الإنشاء", "total": "إجمالي البلاغات",
        "open": "بلاغات مفتوحة", "closed": "بلاغات محلولة", "no_image": "لا يوجد مرفق بصري",
        "no_issues": "لا توجد إشكاليات خلال هذه الفترة", "type": "الأولوية",
        "category": "القسم", "reporter": "المبلّغ",
    },
    "en": {
        "period": "Period", "generated": "Generated", "total": "Total reports",
        "open": "Open reports", "closed": "Resolved reports", "no_image": "No visual attachment",
        "no_issues": "No issues in this period", "type": "Priority",
        "category": "Category", "reporter": "Reporter",
    },
    "tr": {
        "period": "Dönem", "generated": "Oluşturulma", "total": "Toplam bildirim",
        "open": "Açık bildirim", "closed": "Çözülen bildirim", "no_image": "Görsel ek yok",
        "no_issues": "Bu dönemde sorun yok", "type": "Öncelik",
        "category": "Departman", "reporter": "Bildiren",
    },
}

DEPARTMENT_COLORS = {
    "lab": ("#7c3aed", "#ede9fe"),
    "secondary_packaging": ("#ea580c", "#ffedd5"),
    "production": ("#2563eb", "#dbeafe"),
}


def _value(value) -> str:
    return getattr(value, "value", str(value)).split(".")[-1]


def _labels(language: str) -> dict[str, str]:
    return LABELS.get(language, LABELS["en"])


def _image_bytes(media_url: str | None) -> bytes | None:
    if not media_url:
        return None
    parsed = urlparse(media_url)
    try:
        if parsed.scheme in {"http", "https"}:
            request = Request(media_url, headers={"User-Agent": "D1-report-generator/2.0"})
            with urlopen(request, timeout=15) as response:
                return response.read()
        path = Path(media_url.lstrip("/\\"))
        if not path.is_absolute():
            path = BASE_UPLOADS_DIR.parent / path
        return path.read_bytes() if path.is_file() else None
    except (OSError, ValueError) as error:
        logger.warning("Unable to embed report image %s: %s", media_url, error)
        return None


def _image_src(media_url: str | None) -> str:
    data = _image_bytes(media_url)
    if not data:
        return ""
    mime = mimetypes.guess_type(urlparse(media_url or "").path)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _font_faces() -> str:
    faces = []
    for filename, weight in (("Cairo-Regular.ttf", 400), ("Cairo-Bold.ttf", 700)):
        path = FONT_DIR / filename
        if path.is_file():
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            faces.append(
                f"@font-face {{ font-family: Cairo; font-style: normal; font-weight: {weight}; "
                f"src: url(data:font/ttf;base64,{encoded}) format('truetype'); }}"
            )
    return "\n".join(faces)


def _render_template(values: dict[str, str]) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in values.items():
        template = template.replace("{{ " + key + " }}", value)
    return template


def _issue_card(issue: Issue, labels: dict[str, str], language: str) -> str:
    status = _value(issue.status)
    status_label = {
        "open": labels["open"], "closed": labels["closed"],
        "in_progress": "قيد المعالجة" if language == "ar" else "In progress",
        "reopened": "معاد فتحها" if language == "ar" else "Reopened",
    }.get(status, status.replace("_", " ").title())
    image = _image_src(getattr(issue, "image_url", None) or getattr(issue, "media_url", None))
    image_html = (
        f'<img class="issue-image" src="{html.escape(image, quote=True)}" alt="{html.escape(labels["no_image"])}">'
        if image else f'<div class="image-placeholder">{html.escape(labels["no_image"])}</div>'
    )
    created = issue.created_at.strftime("%Y-%m-%d %H:%M") if issue.created_at else "-"
    reporter = issue.creator.name if issue.creator else "-"
    return f"""
      <article class="issue-card">
        <div class="issue-header">
          <span class="issue-id">#{html.escape(str(issue.id))}</span>
          <span class="issue-title">{html.escape(issue.title or "-")}</span>
          <span class="issue-date">{html.escape(created)}</span>
          <span class="status {html.escape(status)}">{html.escape(status_label)}</span>
        </div>
        <div class="issue-body">
          <div class="issue-content">
            <div class="description">{html.escape((issue.description or "-").strip())}</div>
            <div class="metadata">
              <span>{html.escape(labels["type"])}: {html.escape(_value(issue.type))}</span>
              <span>{html.escape(labels["category"])}: {html.escape((issue.category or "-").replace("_", " ").title())}</span>
              <span>{html.escape(labels["reporter"])}: {html.escape(reporter)}</span>
            </div>
          </div>
          <div class="image-wrap">{image_html}</div>
        </div>
      </article>
    """


def build_report_html(
    title: str,
    department: str,
    issues: Iterable[Issue],
    language: str = "ar",
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    issue_list = list(issues)
    labels = _labels(language)
    primary, soft = DEPARTMENT_COLORS.get(department, ("#00a89b", "#ccfbf1"))
    cards = "".join(_issue_card(issue, labels, language) for issue in issue_list)
    if not cards:
        cards = f'<div class="empty">{html.escape(labels["no_issues"])}</div>'
    department_label = department.replace("_", " ").title()
    values = {
        "direction": "rtl" if language == "ar" else "ltr",
        "language": html.escape(language),
        "font_faces": _font_faces(),
        "department_color": primary,
        "department_background": soft,
        "department_label": html.escape(department_label),
        "title": html.escape(title),
        "period_label": html.escape(labels["period"]),
        "start_date": html.escape(start_date or "-"),
        "end_date": html.escape(end_date or "-"),
        "generated_label": html.escape(labels["generated"]),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "reporter_label": html.escape(labels["reporter"]),
        "reporter_name": html.escape(
            issue_list[0].creator.name if issue_list and issue_list[0].creator else "-"
        ),
        "total_label": html.escape(labels["total"]),
        "open_label": html.escape(labels["open"]),
        "closed_label": html.escape(labels["closed"]),
        "total_count": str(len(issue_list)),
        "open_count": str(sum(_value(issue.status) == "open" for issue in issue_list)),
        "closed_count": str(sum(_value(issue.status) == "closed" for issue in issue_list)),
        "issue_cards": cards,
    }
    return _render_template(values)


def generate_report_pdf(
    title: str,
    department: str,
    issues: Iterable[Issue],
    language: str = "ar",
    start_date: str | None = None,
    end_date: str | None = None,
    output_dir: str | None = None,
) -> str:
    issue_list = list(issues)
    period = ""
    if start_date:
        try:
            parsed = datetime.strptime(start_date[:10], "%Y-%m-%d")
            period = f"_{parsed.year}_{parsed.month:02d}"
        except ValueError:
            logger.warning("Invalid report start date for filename: %s", start_date)
    safe_department = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in department)
    output_path = Path(output_dir or REPORTS_DIR) / f"{safe_department}{period}_{uuid.uuid4().hex}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = generate_pdf_from_html(
        build_report_html(title, department, issue_list, language, start_date, end_date)
    )
    output_path.write_bytes(pdf_bytes)
    if output_path.stat().st_size < 1000:
        raise RuntimeError("Chromium produced an invalid PDF")
    return str(output_path)
