"""Add immutable versioned publication receipts without modifying existing reports."""
from alembic import op
import sqlalchemy as sa

revision = "0003_chat_publication"
down_revision = "0002_chat_review"
branch_labels = None
depends_on = None


def upgrade():
    if "chat_publications" in sa.inspect(op.get_bind()).get_table_names():
        expected = {"draft_id", "version", "room_id", "message_id", "text", "state", "actor_id", "created_at"}
        if {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_publications")} != expected:
            raise RuntimeError("Unexpected publication schema")
        return
    op.create_table("chat_publications",
        sa.Column("draft_id", sa.String(64), sa.ForeignKey("chat_drafts.id"), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("room_id", sa.String(100), nullable=False),
        sa.Column("message_id", sa.String(100), nullable=False, unique=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade():
    raise RuntimeError("Restore a verified backup; publication audit records must not be deleted.")
