"""Add the first tenant-owned hosted resource."""

import sqlalchemy as sa
from alembic import op

revision = "h0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hosted_dictionaries",
        sa.Column("owner_key", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hosted_dictionaries")
