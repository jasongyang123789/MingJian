"""Add proposal review state to direction_mappings (option C).

LLM-proposed directions are stored as ``direction_mappings`` rows
with origin ``llm_proposal``. Two columns carry the review workflow:

- ``status``: ``active`` (usable for generation), ``proposed``
  (awaiting an explicit human accept/reject), or ``rejected``
  (retained for audit, never used). Existing rows backfill to
  ``active`` via the server default, preserving Sprint 13/14
  behavior exactly: generation resolves only ``active`` rows.
- ``proposal_record``: nullable JSON pinning the proposal's
  provenance (rationale, key variables, model, template id and
  version, proposal hash), mirroring ``rule_record`` on derived
  rows. NULL on every non-proposal row.

Revision ID: 0041_direction_proposal_status
Revises: 0040_seminar_synthesize_leases
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_direction_proposal_status"
down_revision = "0040_seminar_synthesize_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("direction_mappings", recreate="auto") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(16), nullable=False, server_default="active")
        )
        batch_op.add_column(sa.Column("proposal_record", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("direction_mappings", recreate="auto") as batch_op:
        batch_op.drop_column("proposal_record")
        batch_op.drop_column("status")
