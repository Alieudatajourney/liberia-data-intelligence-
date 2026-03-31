"""
backend/scripts/init_db.py
============================
Creates all database tables defined in app/models/models.py.

Safe to run multiple times — SQLAlchemy's create_all() skips tables
that already exist.  It does NOT drop or modify existing tables.

Run once before loading data:
    python backend/scripts/init_db.py

To verify tables were created (psql):
    \\dt
"""

import sys
import logging
from pathlib import Path

SCRIPT_DIR  = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.logging_config import configure_logging
from app.db.session import engine, Base

# Import models so SQLAlchemy registers them in Base.metadata.
# Without this import, create_all() would create zero tables.
import app.models.models  # noqa: F401

configure_logging()
logger = logging.getLogger(__name__)


def main() -> int:
    logger.info("Creating database tables...")
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logger.error("Failed to create tables: %s", exc)
        return 1

    logger.info("Tables created (or already existed):")
    for table in Base.metadata.sorted_tables:
        logger.info("  ✓ %s", table.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
