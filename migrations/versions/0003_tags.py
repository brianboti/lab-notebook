"""Tags on experiments (an added column: the version still serving keeps working, so a rollback stays safe).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("tags", sa.String(200), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("experiments", "tags")
