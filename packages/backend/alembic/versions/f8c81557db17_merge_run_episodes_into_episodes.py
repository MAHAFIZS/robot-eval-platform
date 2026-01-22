"""merge run_episodes into episodes

Revision ID: f8c81557db17
Revises: a47b06c41451
Create Date: 2026-01-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f8c81557db17"
down_revision: Union[str, Sequence[str], None] = "a47b06c41451"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Ensure episodes has the richer columns used by run_episodes
    op.execute(sa.text("""
    ALTER TABLE episodes
        ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'running',
        ADD COLUMN IF NOT EXISTS metrics_json JSONB,
        ADD COLUMN IF NOT EXISTS error_message TEXT,
        ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ DEFAULT now(),
        ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
    """))

    # 2) Copy data from run_episodes -> episodes ONLY IF run_episodes exists
    op.execute(sa.text("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'run_episodes'
        ) THEN
            INSERT INTO episodes (
                run_id,
                episode_index,
                status,
                metrics_json,
                error_message,
                started_at,
                ended_at
            )
            SELECT
                re.run_id,
                re.episode_index,
                re.status,
                re.metrics_json,
                re.error_message,
                re.started_at,
                re.ended_at
            FROM run_episodes re
            ON CONFLICT (run_id, episode_index) DO UPDATE SET
                status = EXCLUDED.status,
                metrics_json = EXCLUDED.metrics_json,
                error_message = EXCLUDED.error_message,
                started_at = EXCLUDED.started_at,
                ended_at = EXCLUDED.ended_at;

            DROP TABLE run_episodes;
        END IF;
    END $$;
    """))

    # 3) Helpful indexes for comparisons
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_episodes_run_id_status ON episodes(run_id, status);"))



def downgrade() -> None:
    # Recreate run_episodes table and move the data back (best-effort)
    op.execute(sa.text("""
    CREATE TABLE IF NOT EXISTS run_episodes (
        id SERIAL PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        episode_index INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'running',
        metrics_json JSONB,
        error_message TEXT,
        started_at TIMESTAMPTZ DEFAULT now(),
        ended_at TIMESTAMPTZ
    );
    """))

    op.execute(sa.text("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_run_episode
    ON run_episodes (run_id, episode_index);
    """))

    op.execute(sa.text("""
    INSERT INTO run_episodes (run_id, episode_index, status, metrics_json, error_message, started_at, ended_at)
    SELECT run_id, episode_index, status, metrics_json, error_message, started_at, ended_at
    FROM episodes
    ON CONFLICT (run_id, episode_index) DO UPDATE SET
        status = EXCLUDED.status,
        metrics_json = EXCLUDED.metrics_json,
        error_message = EXCLUDED.error_message,
        started_at = EXCLUDED.started_at,
        ended_at = EXCLUDED.ended_at;
    """))

    op.execute(sa.text("DROP INDEX IF EXISTS ix_episodes_run_id_status;"))
