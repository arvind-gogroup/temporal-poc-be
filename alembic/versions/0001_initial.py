"""initial review_workflows table

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_workflows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workflow_id", sa.String(255), nullable=False),
        sa.Column("employee_id", sa.String(255), nullable=False),
        sa.Column("lead_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="INITIATED"),
        sa.Column("form_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("rating", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index("ix_review_workflows_workflow_id", "review_workflows", ["workflow_id"], unique=True)
    op.create_index("ix_review_workflows_employee_id", "review_workflows", ["employee_id"])
    op.create_index("ix_review_workflows_lead_id", "review_workflows", ["lead_id"])
    op.create_index("ix_review_workflows_status", "review_workflows", ["status"])
    op.create_index("ix_review_workflows_created_at_desc", "review_workflows", ["created_at"])

    # Auto-update updated_at on every row update
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER review_workflows_updated_at
        BEFORE UPDATE ON review_workflows
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS review_workflows_updated_at ON review_workflows;")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at;")
    op.drop_index("ix_review_workflows_created_at_desc", table_name="review_workflows")
    op.drop_index("ix_review_workflows_status", table_name="review_workflows")
    op.drop_index("ix_review_workflows_lead_id", table_name="review_workflows")
    op.drop_index("ix_review_workflows_employee_id", table_name="review_workflows")
    op.drop_index("ix_review_workflows_workflow_id", table_name="review_workflows")
    op.drop_table("review_workflows")
