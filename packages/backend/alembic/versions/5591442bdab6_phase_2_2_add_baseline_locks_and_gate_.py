"""
phase 2.2 add baseline locks and gate evaluations

Revision ID: 5591442bdab6
Revises: ddbaade0ca28
Create Date: 2026-01-26 18:32:15.872534
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "5591442bdab6"
down_revision: Union[str, Sequence[str], None] = "ddbaade0ca28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Baseline locks: one baseline per (suite_id, dataset_id, backend)
    op.create_table(
        "baseline_locks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("suite_id", sa.Integer(), sa.ForeignKey("suites.id", ondelete="CASCADE"), nullable=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True),
        sa.Column("backend", sa.Text(), nullable=False),
        sa.Column("baseline_run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ux_baseline_scope",
        "baseline_locks",
        ["suite_id", "dataset_id", "backend"],
        unique=True,
    )

    # 2) Gate evaluations: decision results for candidate vs baseline
    op.create_table(
        "gate_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("baseline_run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),  # PASS | REGRESSION | ERROR | SKIPPED
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ux_gate_pair",
        "gate_evaluations",
        ["baseline_run_id", "candidate_run_id"],
        unique=True,
    )
    op.create_index(
        "ix_gate_candidate",
        "gate_evaluations",
        ["candidate_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_gate_candidate", table_name="gate_evaluations")
    op.drop_index("ux_gate_pair", table_name="gate_evaluations")
    op.drop_table("gate_evaluations")

    op.drop_index("ux_baseline_scope", table_name="baseline_locks")
    op.drop_table("baseline_locks")
