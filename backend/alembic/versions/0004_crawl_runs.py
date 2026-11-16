"""crawl_runs table

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created", sa.Integer(), nullable=True),
        sa.Column("seen", sa.Integer(), nullable=True),
        sa.Column("skipped_no_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_runs_started_at", "crawl_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_crawl_runs_started_at", table_name="crawl_runs")
    op.drop_table("crawl_runs")
