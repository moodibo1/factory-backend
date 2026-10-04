from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv
import os

load_dotenv()

def normalize_database_url(database_url: str | None) -> str | None:
    """Return a SQLAlchemy URL with an explicitly available PostgreSQL driver."""
    if not database_url:
        return database_url

    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql+psycopg2://"):
        return database_url
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    return database_url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL"))

# Supabase Pooler fix: disable prepared statements in connect_args for PgBouncer
connect_args = {}
if DATABASE_URL and "pooler.supabase.com" in DATABASE_URL and DATABASE_URL.startswith("postgresql+psycopg://"):
    connect_args["prepare_threshold"] = None

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required to initialize the database engine")

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
