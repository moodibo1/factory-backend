import sqlite3
import psycopg2
from urllib.parse import urlparse
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

pg_queries = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP;",
    # التعديلات الجديدة الخاصة بالأقسام
    "ALTER TABLE users DROP COLUMN IF EXISTS category;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS categories JSONB DEFAULT '[]'::jsonb;",
    "DELETE FROM monthly_reports WHERE id IN ("
    "SELECT id FROM ("
    "SELECT id, ROW_NUMBER() OVER (PARTITION BY department, month, year ORDER BY created_at DESC NULLS LAST, id DESC) AS row_num "
    "FROM monthly_reports"
    ") duplicates WHERE row_num > 1"
    ");",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_monthly_report_department_month_year ON monthly_reports (department, month, year);"
]

if DATABASE_URL.startswith("postgres"):
    print(f"Connecting to PostgreSQL...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    for q in pg_queries:
        try:
            cursor.execute(q)
            print(f"Success: {q}")
        except Exception as e:
            print(f"Skipped/Error: {e}")
    cursor.close()
    conn.close()
print("Migration completed.")