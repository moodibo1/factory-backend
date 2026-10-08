from __future__ import annotations

import logging
import os



logger = logging.getLogger(__name__)


def generate_pdf_from_html(html_content: str) -> bytes:
    """Render HTML to PDF with bundled Chromium; no native system PDF libraries."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "The Playwright Python package is not installed in the active interpreter. "
            "Install backend requirements with 'python -m pip install -r requirements.txt'."
        ) from error

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1024},
                    device_scale_factor=1,
                )
                page.set_content(html_content, wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                page.wait_for_function(
                    "() => Array.from(document.images).every((image) => image.complete)"
                )
                return page.pdf(
                    format="A4",
                    landscape=True,
                    print_background=True,
                    prefer_css_page_size=True,
                    margin={
                        "top": "10mm",
                        "right": "10mm",
                        "bottom": "10mm",
                        "left": "10mm",
                    },
                )
            finally:
                browser.close()
    except PlaywrightError as error:
        logger.exception("Chromium PDF rendering failed")
        raise RuntimeError(
            "Chromium PDF rendering is unavailable. Run 'python -m playwright install chromium'."
        ) from error
