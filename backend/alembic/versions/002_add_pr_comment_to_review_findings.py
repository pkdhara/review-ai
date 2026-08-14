"""Add pr_comment to review_findings

Revision ID: 002
Revises: 001
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_findings", sa.Column("pr_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("review_findings", "pr_comment")
