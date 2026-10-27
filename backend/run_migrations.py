"""
Database migration runner: `alembic upgrade head`, nothing else.

The schema is owned by Alembic. This never calls Base.metadata.create_all and
never stamps a failed database as up to date.

Usage:
    python run_migrations.py
"""

import logging
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

logger = logging.getLogger("migration_runner")


def run_database_migrations() -> None:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    logger.info("Running alembic upgrade head")
    command.upgrade(cfg, "head")
    logger.info("Database schema is at head")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_database_migrations()
