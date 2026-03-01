"""SQLite session management with auto table creation."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engine.db.models import Base


def init_db(db_path: str) -> sessionmaker[Session]:
    """Create all tables and return a session factory.

    Safe to call on every run — only creates tables if they don't exist.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
