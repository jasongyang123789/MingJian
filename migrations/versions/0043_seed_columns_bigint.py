"""Widen seed columns to BigInteger (fix batch 3).

``derive_sub_seed`` returns 63-bit integers, and they land in
``simulation_runs.seed`` for Monte Carlo trials and robustness
threshold-search probes. ``Integer`` is 32-bit on Postgres, so the
trial-row flush failed with ``integer out of range`` — a bug SQLite
tests could never catch, because SQLite integers are always 64-bit
(Docker retry 6, bug 2). ``calibration_fits.seed`` takes the same
widening: its fit-request seed is an unbounded int, so a 63-bit value
can reach it through the public API.

The seed values themselves are unchanged: narrowing the derivation to
31 bits would change RNG streams and stored determinism hashes, so the
columns widen instead. SQLite behavior is unchanged (its integers were
already 64-bit).

Revision ID: 0043_seed_columns_bigint
Revises: 0042_direction_override_record
Create Date: 2026-11-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_seed_columns_bigint"
down_revision = "0042_direction_override_record"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("simulation_runs", recreate="auto") as batch_op:
        batch_op.alter_column(
            "seed",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
    with op.batch_alter_table("calibration_fits", recreate="auto") as batch_op:
        batch_op.alter_column(
            "seed",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("calibration_fits", recreate="auto") as batch_op:
        batch_op.alter_column(
            "seed",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
    with op.batch_alter_table("simulation_runs", recreate="auto") as batch_op:
        batch_op.alter_column(
            "seed",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
