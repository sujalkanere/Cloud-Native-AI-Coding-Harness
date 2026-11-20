"""
Alembic migration runner for Cloud-Native AI Coding Harness.
Adheres strictly to Spec §7: migrations run automatically on backend start.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

logger = logging.getLogger(__name__)


def run_migrations_sync(database_url: str) -> None:
    """Synchronously executes Alembic upgrade head using alembic.ini."""
    # Find backend directory containing alembic.ini
    current_file = Path(__file__).resolve()
    # backend/app/infrastructure/database/migrations.py -> backend/
    backend_dir = current_file.parents[3]
    ini_path = backend_dir / "alembic.ini"

    if not ini_path.is_file():
        raise FileNotFoundError(f"Alembic config not found at {ini_path}")

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    logger.info("Executing Alembic migrations on %s...", database_url.split("@")[-1])
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations completed successfully.")


async def run_migrations(database_url: str) -> None:
    """Asynchronously runs Alembic migrations in a background thread."""
    await asyncio.to_thread(run_migrations_sync, database_url)
