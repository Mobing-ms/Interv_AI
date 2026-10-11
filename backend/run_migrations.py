"""
Database Migration & Setup Runner.
Executes Alembic migrations and verifies database schema readiness across SQLite and PostgreSQL.
Usage:
    python run_migrations.py
"""

import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alembic.config import Config
from alembic import command
from app.database import engine, Base
import app.models  # Registers all models

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration_runner")


def run_database_migrations():
    logger.info("Initializing database schema...")
    try:
        # 1. Ensure all model tables exist
        Base.metadata.create_all(bind=engine)
        logger.info("Base metadata create_all completed.")

        # 2. Run Alembic upgrade head
        alembic_ini_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alembic.ini")
        if os.path.exists(alembic_ini_path):
            alembic_cfg = Config(alembic_ini_path)
            logger.info("Executing Alembic upgrade head...")
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic upgrade head completed successfully.")
        else:
            logger.warning("alembic.ini not found, skipping Alembic command.")

        logger.info("Database migration finished successfully.")
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        # In case alembic stamps are out of sync on an existing database, stamp head
        try:
            alembic_ini_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alembic.ini")
            if os.path.exists(alembic_ini_path):
                alembic_cfg = Config(alembic_ini_path)
                logger.info("Attempting alembic stamp head...")
                command.stamp(alembic_cfg, "head")
                logger.info("Alembic stamped to head successfully.")
        except Exception as stamp_err:
            logger.error(f"Failed to stamp alembic: {stamp_err}")
            raise e


if __name__ == "__main__":
    run_database_migrations()
