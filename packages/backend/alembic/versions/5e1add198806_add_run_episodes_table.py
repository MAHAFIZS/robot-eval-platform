"""add run_episodes table

Revision ID: 5e1add198806
Revises: 
Create Date: 2026-01-19 09:54:06.270579

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e1add198806'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE run_episodes (
            id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            episode_index INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            metrics_json JSONB,
            error_message TEXT,
            started_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            ended_at TIMESTAMP WITH TIME ZONE
        );
    """))

    op.execute(sa.text("""
        CREATE UNIQUE INDEX uq_run_episode
        ON run_episodes (run_id, episode_index);
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS run_episodes;"))

