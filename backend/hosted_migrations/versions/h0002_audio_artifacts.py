"""Track private audio and retryable storage operations."""

import sqlalchemy as sa
from alembic import op

revision = "h0002"
down_revision = "h0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hosted_artifacts",
        sa.Column("owner_key", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("media_type", sa.String(24), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("state IN ('pending','ready','deleting','deleted')"),
    )
    op.create_index("ix_hosted_artifacts_expiry", "hosted_artifacts", ["expires_at"])
    op.create_index("ix_hosted_artifacts_state", "hosted_artifacts", ["state"])


def downgrade() -> None:
    op.drop_table("hosted_artifacts")
