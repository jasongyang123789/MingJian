"""Add formulas column to variable_templates for Sprint 4 formula graphs.

Revision ID: 0030_variable_template_formulas
Revises: 0029_variable_templates
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_variable_template_formulas"
down_revision = "0029_variable_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "variable_templates",
        sa.Column("formulas", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("variable_templates", "formulas")
