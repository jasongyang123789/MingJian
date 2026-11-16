"""Add seminar audit events + chair briefs tables (Sprint 18).

Two tables for seminar hardening and observability (design doc
``seminar-mechanism-design.md`` §10–§11; S18 directives 2026-11-16):
``seminar_audit_events`` (the append-only flight recorder: stage-call
attempts, retries, budget exhaustions, fallbacks, queue waits, status
transitions, chair-brief production, synthesis submissions, report
writes, synthesis failures, refusals) and ``seminar_chair_briefs``
(versioned agent-chair briefs pinning the pre-pass items a chair
submission is validated against).

Revision ID: 0039_seminar_audit_chair_briefs
Revises: 0038_seminar_tables
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_seminar_audit_chair_briefs"
down_revision = "0038_seminar_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seminar_audit_events",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("seminar_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=True),
        sa.Column("stage", sa.String(120), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=True),
        sa.Column("stage_call_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seminar_id"], ["seminars.id"]),
        sa.UniqueConstraint(
            "seminar_id", "seq", name="uq_seminar_audit_events_seminar_seq"
        ),
    )
    op.create_index("ix_seminar_audit_events_seminar_id", "seminar_audit_events", ["seminar_id"])
    op.create_table(
        "seminar_chair_briefs",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("seminar_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=False),
        sa.Column("brief_hash", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seminar_id"], ["seminars.id"]),
        sa.UniqueConstraint(
            "seminar_id", "version", name="uq_seminar_chair_briefs_seminar_version"
        ),
    )
    op.create_index("ix_seminar_chair_briefs_seminar_id", "seminar_chair_briefs", ["seminar_id"])


def downgrade() -> None:
    op.drop_index("ix_seminar_chair_briefs_seminar_id", table_name="seminar_chair_briefs")
    op.drop_table("seminar_chair_briefs")
    op.drop_index("ix_seminar_audit_events_seminar_id", table_name="seminar_audit_events")
    op.drop_table("seminar_audit_events")
