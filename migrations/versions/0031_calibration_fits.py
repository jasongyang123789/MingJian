"""Add calibration_fits table for Sprint 5 ridge-to-prior fits.

Revision ID: 0031_calibration_fits
Revises: 0030_variable_template_formulas
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_calibration_fits"
down_revision = "0030_variable_template_formulas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calibration_fits",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("domain_id", sa.String(64), nullable=False),
        sa.Column("source_template_id", sa.String(200)),
        sa.Column("calibrated_template_id", sa.String(36)),
        sa.Column("metric", sa.String(120)),
        sa.Column("ridge_strength", sa.Float(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("bootstrap_draws", sa.Integer(), nullable=False),
        sa.Column("level", sa.Float(), nullable=False),
        sa.Column("source_run_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("n_observations", sa.Integer(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("inputs_hash", sa.String(80), nullable=False),
        sa.Column("loo_rmse", sa.Float()),
        sa.Column("application", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_calibration_fits_kind", "calibration_fits", ["kind"])
    op.create_index("ix_calibration_fits_domain_id", "calibration_fits", ["domain_id"])
    op.create_index(
        "ix_calibration_fits_source_template_id", "calibration_fits", ["source_template_id"]
    )
    op.create_index(
        "ix_calibration_fits_calibrated_template_id",
        "calibration_fits",
        ["calibrated_template_id"],
    )


def downgrade() -> None:
    op.drop_table("calibration_fits")
