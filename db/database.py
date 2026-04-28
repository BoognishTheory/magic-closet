from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import Base

DATABASE_URL = "sqlite:///magic_closet.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)

def get_session():
    """Return a new DB session."""
    return SessionLocal()