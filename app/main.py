from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import engine
from app.models.models import Base
from app.routers import auth, issues, dashboard, admin, notifications, security, reports
from app.services.scheduler import start_scheduler, stop_scheduler
import os


Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="Factory Issues API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","https://factory-issues.vercel.app","https://d1wan.org","https://www.d1wan.org"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

app.include_router(auth.router)
app.include_router(issues.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(security.router)
app.include_router(reports.router)

@app.get("/")
def root():
    return {"message": "Factory Issues API is running"}
