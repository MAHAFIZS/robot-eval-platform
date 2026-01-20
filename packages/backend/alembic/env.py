from logging.config import fileConfig

import os
import sys

from sqlalchemy import engine_from_config, pool
from alembic import context

# --- Path setup (kept safe; doesn't hurt even if you don't have an "app" package) ---
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# Alembic Config object (reads alembic.ini)
config = context.config

# Configure Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM models in this project → keep metadata None (manual migrations)
target_metadata = None


def _get_db_url() -> str:
    """
    Prefer DATABASE_URL (same as backend uses in db.py),
    otherwise fall back to alembic.ini sqlalchemy.url.
    """
    return os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without DB connection)."""
    url = _get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connects to DB and applies migrations)."""
    # Override alembic.ini URL with env var if present
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        config.set_main_option("sqlalchemy.url", db_url)

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
