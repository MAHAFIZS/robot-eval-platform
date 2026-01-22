"""add episodes table

Revision ID: a47b06c41451
Revises: f84a4e53351a
Create Date: 2026-01-22 10:04:28.648502

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a47b06c41451'
down_revision: Union[str, Sequence[str], None] = 'f84a4e53351a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename existing run_episodes -> episodes (idempotent)
    op.execute(sa.text("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'run_episodes'
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'episodes'
        ) THEN
            ALTER TABLE run_episodes RENAME TO episodes;
        END IF;
    END $$;
    """))

    # Rename unique index if it exists
    op.execute(sa.text("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'uq_run_episode')
        AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'uq_episodes_run_id_episode_index')
        THEN
            ALTER INDEX uq_run_episode RENAME TO uq_episodes_run_id_episode_index;
        END IF;
    END $$;
    """))

    # Add useful indexes for later comparison queries
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_episodes_run_id ON episodes(run_id);"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_episodes_run_id_status ON episodes(run_id, status);"))


def downgrade() -> None:
    # Drop helper indexes
    op.execute(sa.text("DROP INDEX IF EXISTS ix_episodes_run_id_status;"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_episodes_run_id;"))

    # Rename index back if needed
    op.execute(sa.text("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'uq_episodes_run_id_episode_index')
        AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'uq_run_episode')
        THEN
            ALTER INDEX uq_episodes_run_id_episode_index RENAME TO uq_run_episode;
        END IF;
    END $$;
    """))

    # Rename episodes -> run_episodes (idempotent)
    op.execute(sa.text("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'episodes'
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'run_episodes'
        ) THEN
            ALTER TABLE episodes RENAME TO run_episodes;
        END IF;
    END $$;
    """))