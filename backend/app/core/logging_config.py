"""
backend/app/core/logging_config.py
====================================
Logging setup for the entire application.

Why centralise logging?
  - One place to change format, level, and handlers.
  - All modules get consistent log output.
  - Easy to add file logging or structured JSON logging later.

Usage:
    # In main.py (called once at startup)
    from app.core.logging_config import configure_logging
    configure_logging()

    # In any other module
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Something happened")
"""

import logging
import sys
from app.core.config import settings

# Log format: timestamp [LEVEL] module_name — message
LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    """
    Configure the root logger.

    Called once from main.py at application startup.
    All loggers created with logging.getLogger(__name__) will
    inherit this configuration automatically.
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Create a handler that writes to stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid adding duplicate handlers if called more than once
    if not root_logger.handlers:
        root_logger.addHandler(handler)

    # Quiet down noisy third-party libraries in development
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.debug else logging.WARNING
    )

    logging.getLogger(__name__).info(
        "Logging configured. Level: %s | Env: %s",
        settings.log_level.upper(),
        settings.app_env,
    )
