"""SCENARIO: a migration that works on SQLite and fails on Postgres.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE experiment_typo ADD COLUMN priority integer")


def downgrade() -> None:
    pass
