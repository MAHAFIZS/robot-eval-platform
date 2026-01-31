"""add run label and notes

Revision ID: 1fcf9559067d
Revises: 5591442bdab6
Create Date: 2026-01-27 12:09:25.841049

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1fcf9559067d'
down_revision: Union[str, Sequence[str], None] = '5591442bdab6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("label", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("notes", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("runs", "notes")
    op.drop_column("runs", "label")

