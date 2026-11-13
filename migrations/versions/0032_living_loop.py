"""Add living-strategy loop tables for Sprint 9 (monitor -> re-simulate).

Revision ID: 0032_living_loop
Revises: 0031_calibration_fits
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_living_loop"
down_revision = "0031_calibration_fits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_loops",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("baseline_run_id", sa.String(36), nullable=False),
        sa.Column("domain_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("triggers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["baseline_run_id"], ["simulation_runs.id"]),
    )
    op.create_index("ix_strategy_loops_baseline_run_id", "strategy_loops", ["baseline_run_id"])
    op.create_index("ix_strategy_loops_domain_id", "strategy_loops", ["domain_id"])

    op.create_table(
        "loop_observations",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("loop_id", sa.String(36), nullable=False),
        sa.Column("field", sa.String(120), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_claim_id", sa.String(36)),
        sa.Column("source_note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["loop_id"], ["strategy_loops.id"]),
    )
    op.create_index("ix_loop_observations_loop_id", "loop_observations", ["loop_id"])
    op.create_index("ix_loop_observations_field", "loop_observations", ["field"])
    op.create_index("ix_loop_observations_observed_at", "loop_observations", ["observed_at"])
    op.create_index(
        "ix_loop_observations_source_claim_id", "loop_observations", ["source_claim_id"]
    )

    op.create_table(
        "loop_iterations",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("loop_id", sa.String(36), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="open"),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_cutoff", sa.DateTime(timezone=True)),
        sa.Column("window", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("trigger_evaluations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("resimulation", sa.JSON()),
        sa.Column("comparison", sa.JSON()),
        sa.Column("decision", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["loop_id"], ["strategy_loops.id"]),
        sa.UniqueConstraint("loop_id", "index"),
    )
    op.create_index("ix_loop_iterations_loop_id", "loop_iterations", ["loop_id"])


def downgrade() -> None:
    op.drop_table("loop_iterations")
    op.drop_table("loop_observations")
    op.drop_table("strategy_loops")
