"""partial unique identity: (source, external_job_id)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the PBI-1 non-unique lookup index; the unique index below serves every
    # lookup the old one did. `postgresql_where` encodes the partial predicate.
    op.drop_index("ix_jobs_source_external_job_id", table_name="jobs")
    op.create_index(
        "uq_jobs_source_external_job_id",
        "jobs",
        ["source", "external_job_id"],
        unique=True,
        postgresql_where=sa.text("external_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_source_external_job_id", table_name="jobs")
    op.create_index(
        "ix_jobs_source_external_job_id", "jobs", ["source", "external_job_id"]
    )
