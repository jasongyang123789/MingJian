"""Add seminar tables (Sprint 16).

Five tables for the multi-model seminar mechanism (design doc
``seminar-mechanism-design.md`` §9), created in one migration:
``seminars`` (frozen case snapshot + roster + config + status),
``seminar_rounds`` (per-model rounds: analysis stages + reflection),
``seminar_board`` (append-only digests with a per-seminar monotonic
seq), ``seminar_finals`` (per-model final verdicts), and
``seminar_reports`` (versioned reports — table only in S16; the
synthesize behavior that writes it is S17).

Revision ID: 0038_seminar_tables
Revises: 0037_variable_template_assumption_data
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_seminar_tables"
down_revision = "0037_variable_template_assumption_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seminars",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("case_snapshot", sa.JSON(), nullable=False),
        sa.Column("case_snapshot_hash", sa.String(80), nullable=False),
        sa.Column("roster", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("chair_model", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["simulation_runs.id"]),
    )
    op.create_index("ix_seminars_run_id", "seminars", ["run_id"])
    op.create_table(
        "seminar_rounds",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("seminar_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("board_snapshot_seq", sa.Integer(), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("reflection", sa.JSON(), nullable=True),
        sa.Column("reflection_stage", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seminar_id"], ["seminars.id"]),
        sa.UniqueConstraint(
            "seminar_id",
            "model_id",
            "round_no",
            name="uq_seminar_rounds_seminar_model_round",
        ),
    )
    op.create_index("ix_seminar_rounds_seminar_id", "seminar_rounds", ["seminar_id"])
    op.create_table(
        "seminar_board",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("seminar_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("digest", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seminar_id"], ["seminars.id"]),
        sa.UniqueConstraint("seminar_id", "seq", name="uq_seminar_board_seminar_seq"),
    )
    op.create_index("ix_seminar_board_seminar_id", "seminar_board", ["seminar_id"])
    op.create_table(
        "seminar_finals",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("seminar_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=False),
        sa.Column("verdict", sa.JSON(), nullable=False),
        sa.Column("stage", sa.JSON(), nullable=False),
        sa.Column("board_snapshot_seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seminar_id"], ["seminars.id"]),
        sa.UniqueConstraint("seminar_id", "model_id", name="uq_seminar_finals_seminar_model"),
    )
    op.create_index("ix_seminar_finals_seminar_id", "seminar_finals", ["seminar_id"])
    op.create_table(
        "seminar_reports",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("seminar_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("clusters", sa.JSON(), nullable=True),
        sa.Column("synthesis", sa.JSON(), nullable=True),
        sa.Column("computed_metrics", sa.JSON(), nullable=False),
        sa.Column("report_hash", sa.String(80), nullable=False),
        sa.Column("chair_model_id", sa.String(120), nullable=False),
        sa.Column("partial", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["seminar_id"], ["seminars.id"]),
        sa.UniqueConstraint("seminar_id", "version", name="uq_seminar_reports_seminar_version"),
    )
    op.create_index("ix_seminar_reports_seminar_id", "seminar_reports", ["seminar_id"])


def downgrade() -> None:
    op.drop_table("seminar_reports")
    op.drop_table("seminar_finals")
    op.drop_table("seminar_board")
    op.drop_table("seminar_rounds")
    op.drop_table("seminars")
