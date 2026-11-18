"""Add the override record to direction_mappings (option B).

Variable-override directions are stored as ``direction_mappings``
rows with origin ``override``. One column carries their
provenance:

- ``override_record``: nullable JSON pinning the override spec
  (variable id → fixed value), the scenario branch id, the fork
  step, and the override hash, mirroring ``proposal_record`` on
  proposal rows and ``rule_record`` on derived rows. NULL on
  every non-override row.

Revision ID: 0042_direction_override_record
Revises: 0041_direction_proposal_status
Create Date: 2026-11-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_direction_override_record"
down_revision = "0041_direction_proposal_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("direction_mappings", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("override_record", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("direction_mappings", recreate="auto") as batch_op:
        batch_op.drop_column("override_record")
