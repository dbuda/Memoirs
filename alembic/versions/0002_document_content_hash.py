"""Add document content hash for idempotent ingestion.

Revision ID: 0002_content_hash
Revises: 0001_initial
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_content_hash"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_hash", sa.String(64), nullable=True))
    op.execute("UPDATE documents SET content_hash = md5(random()::text) WHERE content_hash IS NULL")
    op.alter_column("documents", "content_hash", nullable=False)
    op.create_index(
        "ix_documents_content_hash",
        "documents",
        ["content_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_column("documents", "content_hash")
