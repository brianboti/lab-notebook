"""The activity feed read back from Pub/Sub.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("message_id", sa.String(100), nullable=False, unique=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("activity")
