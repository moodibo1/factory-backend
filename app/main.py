from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import engine
from app.models.models import Base
from app.routers import auth, issues, dashboard, admin, notifications, security
import os
from sqlalchemy import text


Base.metadata.create_all(bind=engine)

# --- AUTO MIGRATION ---
# Safely add new columns to live database upon boot
with engine.begin() as conn:
    try:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP;"))
    except Exception as e:
        print("Auto-migration skipped or failed:", e)
# ----------------------


app = FastAPI(title="Factory Issues API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth.router)
app.include_router(issues.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(security.router)

@app.get("/")
def root():
    return {"message": "Factory Issues API is running"}
