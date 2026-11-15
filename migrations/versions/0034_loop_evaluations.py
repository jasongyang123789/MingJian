"""Add loop_evaluations table for Sprint 11 (monitoring worker).

The monitoring worker evaluates each loop's active trigger
registration against all recorded observations and records the
outcome here. This table is the worker's only write target: no loop,
iteration, or run row is ever written by a monitoring cycle.

Revision ID: 0034_loop_evaluations
Revises: 0033_calibration_weight_applications
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_loop_evaluations"
down_revision = "0033_calibration_weight_applications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "loop_evaluations",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("loop_id", sa.String(36), nullable=False),
        sa.Column("cycle_id", sa.String(36), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_fingerprint", sa.String(80), nullable=False),
        sa.Column("registration_id", sa.String(36)),
        sa.Column("observation_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("outcomes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["loop_id"], ["strategy_loops.id"]),
    )
    op.create_index("ix_loop_evaluations_loop_id", "loop_evaluations", ["loop_id"])
    op.create_index("ix_loop_evaluations_cycle_id", "loop_evaluations", ["cycle_id"])
    op.create_index(
        "ix_loop_evaluations_registration_id", "loop_evaluations", ["registration_id"]
    )
    op.create_index("ix_loop_evaluations_summary", "loop_evaluations", ["summary"])


def downgrade() -> None:
    op.drop_table("loop_evaluations")
