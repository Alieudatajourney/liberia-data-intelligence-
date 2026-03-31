"""
backend/app/db/session.py
==========================
Database engine and session factory.

Responsibilities:
  - Create the SQLAlchemy engine (one per process).
  - Provide a session factory (SessionLocal).
  - Expose get_db() as a FastAPI dependency.

Why separate this from models?
  - Models import Base from here.
  - Routes import get_db from here.
  - Keeps concerns separated — models describe *what* is stored,
    session describes *how* to connect.

Usage in a route:
    from app.db.session import get_db
    from sqlalchemy.orm import Session
    from fastapi import Depends

    def my_route(db: Session = Depends(get_db)):
        results = db.execute(...)
"""

import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# pool_pre_ping=True: test each connection before using it.
# This prevents "connection closed" errors after the database restarts.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Echo SQL statements to the log only in debug mode
    echo=settings.debug,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
# autocommit=False : you must explicitly call db.commit()
# autoflush=False  : SQLAlchemy won't auto-flush before queries
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------
# All ORM model classes will inherit from Base.
# Defined here so that init_db.py can call Base.metadata.create_all(engine).
Base = declarative_base()


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_db() -> Session:
    """
    Yields a database session and guarantees it is closed after use,
    even if the request raises an exception.

    FastAPI calls this automatically for any route that declares:
        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        logger.debug("DB session closed.")
