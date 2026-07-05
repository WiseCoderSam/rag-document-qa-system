"""drop log_files, log_entries, and incidents tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-05

The log-ingestion / threat-detection feature has been removed from the
application (it was out of scope for the Document Q&A product). These
tables are no longer read or written by any code path, so they're dropped
rather than left behind as dead schema. Dropping them also deletes any
ingested log data — the feature's data has no meaning without the feature.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Children first: incidents and log_entries both FK into log_files.
    op.drop_index(op.f("ix_incidents_severity"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_rule_name"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_mitre_technique"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_mitre_tactic"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_id"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_affected_user"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_affected_ip"), table_name="incidents")
    op.drop_table("incidents")

    op.drop_index(op.f("ix_log_entries_user_name"), table_name="log_entries")
    op.drop_index(op.f("ix_log_entries_severity"), table_name="log_entries")
    op.drop_index(op.f("ix_log_entries_ip_address"), table_name="log_entries")
    op.drop_index(op.f("ix_log_entries_id"), table_name="log_entries")
    op.drop_index(op.f("ix_log_entries_hostname"), table_name="log_entries")
    op.drop_index(op.f("ix_log_entries_event_id"), table_name="log_entries")
    op.drop_table("log_entries")

    op.drop_index(op.f("ix_log_files_id"), table_name="log_files")
    op.drop_table("log_files")


def downgrade() -> None:
    """Downgrade schema — recreates the tables (empty) exactly as revisions f6e45abff578 + 0001 left them."""
    op.create_table(
        "log_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_url", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("uploaded_by", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_log_files_id"), "log_files", ["id"], unique=False)

    op.create_table(
        "log_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_name", sa.String(), nullable=True),
        sa.Column("hostname", sa.String(), nullable=True),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("parsed_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["log_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_log_entries_event_id"), "log_entries", ["event_id"], unique=False)
    op.create_index(op.f("ix_log_entries_hostname"), "log_entries", ["hostname"], unique=False)
    op.create_index(op.f("ix_log_entries_id"), "log_entries", ["id"], unique=False)
    op.create_index(op.f("ix_log_entries_ip_address"), "log_entries", ["ip_address"], unique=False)
    op.create_index(op.f("ix_log_entries_severity"), "log_entries", ["severity"], unique=False)
    op.create_index(op.f("ix_log_entries_user_name"), "log_entries", ["user_name"], unique=False)

    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), server_default="", nullable=False),
        sa.Column("rule_name", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("mitre_technique", sa.String(), nullable=True),
        sa.Column("mitre_tactic", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("affected_user", sa.String(), nullable=True),
        sa.Column("affected_ip", sa.String(), nullable=True),
        sa.Column("log_file_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["log_file_id"], ["log_files.id"], name="fk_incidents_log_file_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_incidents_affected_ip"), "incidents", ["affected_ip"], unique=False)
    op.create_index(op.f("ix_incidents_affected_user"), "incidents", ["affected_user"], unique=False)
    op.create_index(op.f("ix_incidents_id"), "incidents", ["id"], unique=False)
    op.create_index(op.f("ix_incidents_mitre_tactic"), "incidents", ["mitre_tactic"], unique=False)
    op.create_index(op.f("ix_incidents_mitre_technique"), "incidents", ["mitre_technique"], unique=False)
    op.create_index(op.f("ix_incidents_rule_name"), "incidents", ["rule_name"], unique=False)
    op.create_index(op.f("ix_incidents_severity"), "incidents", ["severity"], unique=False)
