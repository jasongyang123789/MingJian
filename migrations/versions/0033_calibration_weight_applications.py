"""Add calibration_weight_applications table for Sprint 10.

Persistent current-weights record: one append-only row per rule-weight
application, chained by supersedes_id. See CalibrationFitRecord /
CalibrationWeightApplicationRecord in domain/models.py.

Revision ID: 0033_calibration_weight_applications
Revises: 0032_living_loop
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_calibration_weight_applications"
down_revision = "0032_living_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calibration_weight_applications",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("domain_id", sa.String(64), nullable=False),
        sa.Column("fit_id", sa.String(36), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("previous_weights", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("supersedes_id", sa.String(36)),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fit_id"], ["calibration_fits.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["calibration_weight_applications.id"]),
    )
    op.create_index(
        "ix_calibration_weight_applications_domain_id",
        "calibration_weight_applications",
        ["domain_id"],
    )
    op.create_index(
        "ix_calibration_weight_applications_fit_id",
        "calibration_weight_applications",
        ["fit_id"],
    )
    op.create_index(
        "ix_calibration_weight_applications_supersedes_id",
        "calibration_weight_applications",
        ["supersedes_id"],
    )


def downgrade() -> None:
    op.drop_table("calibration_weight_applications")
