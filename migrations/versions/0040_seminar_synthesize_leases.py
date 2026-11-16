"""Add the seminar synthesize lease table (Sprint 19).

One table for the distributed synthesize lock (S19 directives
2026-11-16): ``seminar_synthesize_leases`` holds at most one row per
seminar — the row's existence means the lock is held. The lease
provider acquires with an atomic insert-or-takeover dance using only
portable SQL (insert / conditional update / conditional delete), so
the same code path works on SQLite (dev) and Postgres (deploy).

Revision ID: 0040_seminar_synthesize_leases
Revises: 0039_seminar_audit_chair_briefs
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_seminar_synthesize_leases"
down_revision = "0039_seminar_audit_chair_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seminar_synthesize_leases",
        sa.Column("seminar_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("holder_id", sa.String(36), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("holder_label", sa.String(120), nullable=True),
        sa.ForeignKeyConstraint(["seminar_id"], ["seminars.id"]),
    )


def downgrade() -> None:
    op.drop_table("seminar_synthesize_leases")
