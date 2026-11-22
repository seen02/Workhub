"""initial schema with report audit history"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("employees", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(80), nullable=False), sa.Column("team", sa.String(80), nullable=False))
    op.create_index("ix_employees_name", "employees", ["name"], unique=True)
    op.create_table("projects", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(140), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("expected_progress", sa.Integer(), nullable=False))
    op.create_index("ix_projects_name", "projects", ["name"], unique=True)
    op.create_table("tasks", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False), sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False), sa.Column("title", sa.String(180), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("progress", sa.Integer(), nullable=False), sa.Column("expected_progress", sa.Integer(), nullable=False), sa.Column("started_at", sa.Date()), sa.Column("due_date", sa.Date()))
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_index("ix_tasks_employee_id", "tasks", ["employee_id"])
    op.create_table("reports", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False), sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False), sa.Column("raw_message", sa.Text(), nullable=False), sa.Column("structured_summary", sa.Text(), nullable=False), sa.Column("duration_hours", sa.Float()), sa.Column("progress", sa.Integer()), sa.Column("issue", sa.Text()), sa.Column("next_action", sa.String(240)), sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_reports_employee_id", "reports", ["employee_id"])
    op.create_index("ix_reports_task_id", "reports", ["task_id"])
    op.create_index("ix_reports_fingerprint", "reports", ["fingerprint"], unique=True)
    op.create_index("ix_reports_created_at", "reports", ["created_at"])
    op.create_table("report_revisions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), nullable=False), sa.Column("changed_by", sa.String(80), nullable=False), sa.Column("before_data", sa.Text(), nullable=False), sa.Column("after_data", sa.Text(), nullable=False), sa.Column("reason", sa.String(240), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_report_revisions_report_id", "report_revisions", ["report_id"])
    op.create_index("ix_report_revisions_created_at", "report_revisions", ["created_at"])


def downgrade() -> None:
    op.drop_table("report_revisions")
    op.drop_table("reports")
    op.drop_table("tasks")
    op.drop_table("projects")
    op.drop_table("employees")
