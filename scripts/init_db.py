"""Create all tables directly from the ORM models (dev/local convenience).

Production deployments should use Alembic migrations (`alembic upgrade head`)
instead so schema changes are versioned.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.base import Base, engine
import app.database.models  # noqa: F401 registers every table
from app.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    Base.metadata.create_all(engine)
    logger.info("database_initialized", tables=sorted(Base.metadata.tables.keys()))


if __name__ == "__main__":
    main()
