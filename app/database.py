from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv
import os

load_dotenv()


def _detect_driver() -> str:
    """Return the best available PostgreSQL driver name for SQLAlchemy."""
    try:
        import psycopg  # noqa: F401
        return "postgresql+psycopg"
    except ImportError:
        pass
    try:
        import psycopg2  # noqa: F401
        return "postgresql+psycopg2"
    except ImportError:
        pass
    # Bare dialect — let SQLAlchemy decide
    return "postgresql"


def _normalize_url(url: str | None) -> str | None:
    """Rewrite DATABASE_URL to use the detected driver prefix."""
    if not url:
        return url
    driver = _detect_driver()
    # Strip any existing driver suffix
    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            return url.replace(prefix, f"{driver}://", 1)
    return url


DATABASE_URL = _normalize_url(os.getenv("DATABASE_URL"))

# Supabase Pooler fix: disable prepared statements for PgBouncer
connect_args = {}
if DATABASE_URL and "pooler.supabase.com" in DATABASE_URL:
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
