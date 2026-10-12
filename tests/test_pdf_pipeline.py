import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://user:password@localhost/factory")

from app.maintenance import run_monthly_report_batch
from app.reporting import build_report_html
from app.services.pdf_engine import generate_pdf_from_html


class PdfPipelineTests(unittest.TestCase):
    def test_monthly_batch_rejects_invalid_period_before_database_work(self):
        with self.assertRaisesRegex(ValueError, "target_month"):
            run_monthly_report_batch(2026, 13, None)

    def test_report_html_embeds_arabic_font_and_escapes_issue_content(self):
        class Issue:
            id = 7
            title = '<unsafe>'
            description = "الوصف"
            type = "problem"
            category = "lab"
            status = "open"
            created_at = None
            creator = None
            image_url = None
            media_url = None

        rendered = build_report_html("عنوان", "lab", [Issue()], language="ar")
        self.assertIn("font-face", rendered)
        self.assertIn("&lt;unsafe&gt;", rendered)
        self.assertIn("الوصف", rendered)
        self.assertIn('dir="rtl"', rendered)

    def test_pdf_engine_uses_cloud_safe_chromium_flags(self):
        calls = {}

        class Page:
            def set_content(self, *_args, **_kwargs):
                pass

            def evaluate(self, *_args):
                pass

            def wait_for_function(self, *_args):
                pass

            def pdf(self, **_kwargs):
                return b"%PDF"

        class Browser:
            def new_page(self, **_kwargs):
                return Page()

            def close(self):
                pass

        class Chromium:
            def launch(self, **kwargs):
                calls.update(kwargs)
                return Browser()

        class Playwright:
            chromium = Chromium()

        class PlaywrightContext:
            def __enter__(self):
                return Playwright()

            def __exit__(self, *_args):
                pass

        fake_api = types.ModuleType("playwright.sync_api")
        fake_api.Error = RuntimeError
        fake_api.sync_playwright = lambda: PlaywrightContext()
        with mock.patch.dict(sys.modules, {"playwright.sync_api": fake_api}):
            self.assertEqual(generate_pdf_from_html("<html></html>"), b"%PDF")
        self.assertIn("--no-sandbox", calls["args"])
        self.assertIn("--disable-dev-shm-usage", calls["args"])


if __name__ == "__main__":
    unittest.main()
