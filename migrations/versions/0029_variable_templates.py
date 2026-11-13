"""Add variable_templates table for Sprint 2 variable tables.

Revision ID: 0029_variable_templates
Revises: 0028_recommendation_version_integrity
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_variable_templates"
down_revision = "0028_recommendation_version_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "variable_templates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("domain_id", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("state_fields", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("policies", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("variables", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("internal", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.String(length=120), nullable=True),
        sa.Column("preset_id", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_variable_templates_domain_id", "variable_templates", ["domain_id"])
    op.create_index("ix_variable_templates_tenant_id", "variable_templates", ["tenant_id"])
    op.create_index("ix_variable_templates_preset_id", "variable_templates", ["preset_id"])


def downgrade() -> None:
    op.drop_index("ix_variable_templates_preset_id", table_name="variable_templates")
    op.drop_index("ix_variable_templates_tenant_id", table_name="variable_templates")
    op.drop_index("ix_variable_templates_domain_id", table_name="variable_templates")
    op.drop_table("variable_templates")
