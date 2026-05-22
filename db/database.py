from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import Base
from sqlalchemy import create_engine, text

DATABASE_URL = "sqlite:////data/magic_closet.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def run_migrations(engine):
    """Safe column migrations. Skips if column already exists."""
    migrations = [
        "ALTER TABLE players ADD COLUMN daily_customers TEXT",
        "ALTER TABLE players ADD COLUMN shop_name TEXT",
        "ALTER TABLE players ADD COLUMN town_name TEXT",
        "ALTER TABLE players ADD COLUMN name_last_changed_shop DATETIME",
        "ALTER TABLE players ADD COLUMN name_last_changed_town DATETIME",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Column already exists — skip

def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

def get_session():
    """Return a new DB session."""
    return SessionLocal()