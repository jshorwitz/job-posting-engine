"""SQLite session management with auto table creation."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from engine.db.models import Base

logger = logging.getLogger(__name__)


def _migrate_db(engine) -> None:
    """Apply incremental schema migrations to an existing database.

    SQLite doesn't support ALTER TABLE ADD COLUMN IF NOT EXISTS, so we
    attempt each migration and silently skip it if the column already exists.
    """
    migrations = [
        # 2026-04-09: add campaign column to drip_state for multi-sequence support
        "ALTER TABLE drip_state ADD COLUMN campaign VARCHAR(50) DEFAULT 'growth_hire'",
    ]
    with engine.begin() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception:
                # Column already exists — safe to ignore
                pass


def init_db(db_path: str) -> sessionmaker[Session]:
    """Create all tables and return a session factory.

    Safe to call on every run — creates new tables and applies any pending
    schema migrations without dropping existing data.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    _migrate_db(engine)

    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session(settings) -> Session:
    """Return a ready-to-use SQLAlchemy Session for the configured database.

    Convenience helper used by `engine.vector_pipeline` and the hourly
    Vector outreach scheduler in `scripts/x_scheduler.py`. Without this
    function the scheduler crashes hourly with:
        ImportError: cannot import name 'get_session' from 'engine.db.database'
    """
    db_path = getattr(settings, "database_path", None) or getattr(settings, "db_path", "data/outreach.db")
    SessionFactory = init_db(db_path)
    return SessionFactory()
