"""Add assumption_data column to variable_templates for Phase 1.

Revision ID: 0037_variable_template_assumption_data
Revises: 0036_direction_mappings
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_variable_template_assumption_data"
down_revision = "0036_direction_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "variable_templates",
        sa.Column("assumption_data", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("variable_templates", "assumption_data")
