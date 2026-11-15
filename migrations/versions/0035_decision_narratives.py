"""Add decision_narratives and decision_narrative_polishes tables (Sprint 13).

Narratives are versioned, append-only deliverables: regeneration
inserts a new row, never overwrites. The deterministic artifact
lives in decision_narratives; optional LLM polish passes live in
decision_narrative_polishes, strictly separated, so a polish never
mutates the source of truth.

Revision ID: 0035_decision_narratives
Revises: 0034_loop_evaluations
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_decision_narratives"
down_revision = "0034_loop_evaluations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_narratives",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("inputs_hash", sa.String(80), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("artifact", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["simulation_runs.id"]),
    )
    op.create_index("ix_decision_narratives_run_id", "decision_narratives", ["run_id"])
    op.create_index(
        "ix_decision_narratives_run_id_version",
        "decision_narratives",
        ["run_id", "version"],
    )
    op.create_table(
        "decision_narrative_polishes",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("narrative_id", sa.String(36), nullable=False),
        sa.Column("model", sa.String(120)),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(16), nullable=False),
        sa.Column("polished_markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["narrative_id"], ["decision_narratives.id"]),
    )
    op.create_index(
        "ix_decision_narrative_polishes_narrative_id",
        "decision_narrative_polishes",
        ["narrative_id"],
    )


def downgrade() -> None:
    op.drop_table("decision_narrative_polishes")
    op.drop_table("decision_narratives")
