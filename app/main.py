from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import engine
from app.models.models import Base
from app.routers import auth, issues, dashboard, admin, notifications, security
import os


Base.metadata.create_all(bind=engine)


app = FastAPI(title="Factory Issues API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://factory-issues-git-main-ibrahimalone.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000"
    ],
    allow_credentials=True,
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
