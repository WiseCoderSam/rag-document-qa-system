"""add title and log_file_id to incidents

Revision ID: 0001
Revises:
Create Date: 2026-07-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = "f6e45abff578"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("incidents", sa.Column("title", sa.String(), nullable=False, server_default=""))
    op.add_column("incidents", sa.Column("log_file_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.create_foreign_key(
            "fk_incidents_log_file_id", "log_files", ["log_file_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_constraint("fk_incidents_log_file_id", type_="foreignkey")
        batch_op.drop_column("log_file_id")
        batch_op.drop_column("title")
