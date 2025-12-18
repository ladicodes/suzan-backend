from sqlmodel import SQLModel, create_engine, Session
from .config import settings

# Use SQLite by default if DATABASE_URL is not set
DATABASE_URL = getattr(settings, "DATABASE_URL", None) or "sqlite:///./backend.db"

# Render provides DATABASE_URL starting with postgres:// but SQLAlchemy needs postgresql://
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, echo=False)

def init_db():
    SQLModel.metadata.create_all(engine)
