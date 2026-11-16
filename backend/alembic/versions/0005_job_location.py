"""jobs.city and jobs.country

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("city", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("country", sa.Text(), nullable=True))
    op.create_index("ix_jobs_country_city", "jobs", ["country", "city"])


def downgrade() -> None:
    op.drop_index("ix_jobs_country_city", table_name="jobs")
    op.drop_column("jobs", "country")
    op.drop_column("jobs", "city")
