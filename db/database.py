from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from db.models import Base

DATABASE_URL = "sqlite:////data/magic_closet.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def run_migrations(engine):
    """
    Safe column migrations. Each ALTER TABLE is skipped if column already exists.
    Add new migrations here as new columns are added to models.py.
    """
    migrations = [
        # Shop / franchise
        "ALTER TABLE players ADD COLUMN daily_customers TEXT",
        "ALTER TABLE players ADD COLUMN shop_name TEXT",
        "ALTER TABLE players ADD COLUMN town_name TEXT",
        "ALTER TABLE players ADD COLUMN name_last_changed_shop DATETIME",
        "ALTER TABLE players ADD COLUMN name_last_changed_town DATETIME",
        "ALTER TABLE players ADD COLUMN xp INTEGER DEFAULT 0",
        "ALTER TABLE players ADD COLUMN shop_level INTEGER DEFAULT 1",
        # Skill points
        "ALTER TABLE skill_points ADD COLUMN unspent_points INTEGER DEFAULT 0",
        # Character level tracking
        "ALTER TABLE players ADD COLUMN char_level INTEGER DEFAULT 1",
        "ALTER TABLE players ADD COLUMN char_xp INTEGER DEFAULT 0",
        "ALTER TABLE players ADD COLUMN combat_wins INTEGER DEFAULT 0",
        "ALTER TABLE players ADD COLUMN social_wins INTEGER DEFAULT 0",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Column already exists — skip silently


def init_db():
    """Create all tables if they don't exist, then run column migrations."""
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)


def get_session():
    """Return a new DB session."""
    return SessionLocal()
