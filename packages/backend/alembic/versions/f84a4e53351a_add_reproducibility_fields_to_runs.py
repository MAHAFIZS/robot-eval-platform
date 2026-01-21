"""add reproducibility fields to runs

Revision ID: f84a4e53351a
Revises: 5e1add198806
Create Date: 2026-01-20 21:31:54.409302

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f84a4e53351a'
down_revision: Union[str, Sequence[str], None] = '5e1add198806'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("runs", sa.Column("git_commit", sa.String(length=64), nullable=True))
    op.add_column("runs", sa.Column("config_snapshot", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("seed", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("worker_version", sa.String(length=32), nullable=True))


def downgrade():
    op.drop_column("runs", "worker_version")
    op.drop_column("runs", "seed")
    op.drop_column("runs", "config_snapshot")
    op.drop_column("runs", "git_commit")