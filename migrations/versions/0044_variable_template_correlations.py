"""Add correlations column to variable_templates (Phase 2, Track 3).

Variable-correlation specs travel with a template's variable set, so
stored templates persist them alongside variables and formulas. The
run-bindings path needs no migration: bindings live in the run
configuration JSON, and ``VariableSet.correlations`` defaults to ``[]``
there, so old stored bindings parse as independent sampling.

Revision ID: 0044_variable_template_correlations
Revises: 0043_seed_columns_bigint
Create Date: 2026-11-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_variable_template_correlations"
down_revision = "0043_seed_columns_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "variable_templates",
        sa.Column("correlations", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("variable_templates", "correlations")
