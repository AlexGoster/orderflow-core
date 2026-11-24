"""Add administrator flag without granting privileges to existing users."""

import sqlalchemy as sa

from alembic import op

revision = "b163f89d211a"
down_revision = "587376b8170e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
