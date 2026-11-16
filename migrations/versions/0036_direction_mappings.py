"""Add direction_mappings table + narrative mapping-ids column (Sprint 14).

Direction mappings persist direction definitions per anchor run so
narrative generation can resolve directions from stored rows instead
of per-request definitions. Names are unique per anchor run (DB
constraint backs the code-level check). The nullable
``direction_mapping_ids`` column on ``decision_narratives`` records
which mappings a generation resolved its directions from; it stays
NULL for generations from inline definitions and for pre-Sprint-14
rows.

Revision ID: 0036_direction_mappings
Revises: 0035_decision_narratives
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_direction_mappings"
down_revision = "0035_decision_narratives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "direction_mappings",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("anchor_run_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source_run_id", sa.String(36), nullable=False),
        sa.Column("arm", sa.String(16), nullable=False),
        sa.Column("mece_branches", sa.JSON(), nullable=False),
        sa.Column("deliberation_id", sa.String(36)),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("rule_id", sa.String(32)),
        sa.Column("rules_version", sa.String(32)),
        sa.Column("rule_record", sa.JSON()),
        sa.Column("user_edited", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["anchor_run_id"], ["simulation_runs.id"]),
        sa.ForeignKeyConstraint(["source_run_id"], ["simulation_runs.id"]),
        sa.UniqueConstraint(
            "anchor_run_id", "name", name="uq_direction_mappings_anchor_name"
        ),
    )
    op.create_index(
        "ix_direction_mappings_anchor_run_id", "direction_mappings", ["anchor_run_id"]
    )
    with op.batch_alter_table("decision_narratives", recreate="auto") as batch_op:
        batch_op.add_column(
            sa.Column("direction_mapping_ids", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("decision_narratives", recreate="auto") as batch_op:
        batch_op.drop_column("direction_mapping_ids")
    op.drop_table("direction_mappings")
