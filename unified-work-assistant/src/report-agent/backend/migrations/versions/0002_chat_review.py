"""Rocket.Chat source-linked drafts and optimistic revision history."""
from alembic import op
import sqlalchemy as sa

revision = "0002_chat_review"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("progress", existing_type=sa.Integer(), nullable=True)
    # The legacy demo app calls create_all on reload; accept only complete matching tables.
    inspector = sa.inspect(op.get_bind())
    expected = {
        "chat_drafts": {"id", "room_id", "message_id", "author_id", "author_username", "raw_message", "submitted_at", "model", "ai_data", "current_data", "state", "version", "created_at", "updated_at"},
        "chat_draft_items": {"draft_id", "position", "report_id"},
        "chat_draft_revisions": {"id", "draft_id", "actor_id", "version", "action", "before_data", "after_data", "reason", "created_at"},
    }
    present = set(inspector.get_table_names()) & set(expected)
    if present:
        if present != set(expected) or any({c["name"] for c in inspector.get_columns(table)} != cols for table, cols in expected.items()):
            raise RuntimeError("Partial or unexpected review schema; manual review required.")
        return
    op.create_table("chat_drafts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(100), nullable=False),
        sa.Column("message_id", sa.String(100), nullable=False),
        sa.Column("author_id", sa.String(100), nullable=False),
        sa.Column("author_username", sa.String(100), nullable=False),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("ai_data", sa.Text(), nullable=False),
        sa.Column("current_data", sa.Text(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_chat_drafts_author_id", "chat_drafts", ["author_id"])
    op.create_table("chat_draft_items",
        sa.Column("draft_id", sa.String(64), sa.ForeignKey("chat_drafts.id"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), nullable=False, unique=True))
    op.create_table("chat_draft_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("draft_id", sa.String(64), sa.ForeignKey("chat_drafts.id"), nullable=False),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("before_data", sa.Text(), nullable=False),
        sa.Column("after_data", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_chat_draft_revisions_draft_id", "chat_draft_revisions", ["draft_id"])


def downgrade():
    # Do not silently delete source/audit records or replace unknown progress with zero.
    raise RuntimeError("Destructive downgrade is disabled. Restore the verified pre-migration backup instead.")
