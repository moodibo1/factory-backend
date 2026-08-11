import sqlite3
import psycopg2
from urllib.parse import urlparse
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

queries = [
    "ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE users ADD COLUMN verification_code VARCHAR(255);",
    "ALTER TABLE users ADD COLUMN token_expires_at TIMESTAMP;"
]

# We should make this script safe (ignore if column exists).
# In PostgreSQL:
# ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;
# ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR(255);
# ALTER TABLE users ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP;

pg_queries = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP;"
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
