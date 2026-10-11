"""create question_bank_items table

Revision ID: bf5ad75e9047
Revises: ced140aae372
Create Date: 2026-10-11 15:35:03.183240

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'bf5ad75e9047'
down_revision: Union[str, Sequence[str], None] = 'ced140aae372'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = inspector.get_table_names()

    if "question_bank_items" not in existing_tables:
        op.create_table(
            "question_bank_items",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_configs.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("question_hash", sa.String(length=64), nullable=False, index=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("topic", sa.String(length=100), nullable=False, index=True),
            sa.Column("subtopic", sa.String(length=100), nullable=True),
            sa.Column("difficulty", sa.String(length=50), nullable=False),
            sa.Column("question_type", sa.String(length=50), nullable=False),
            sa.Column("expected_keywords", sa.JSON(), nullable=False),
            sa.Column("ideal_answer_points", sa.JSON(), nullable=False),
            sa.Column("max_time_seconds", sa.Integer(), nullable=False, server_default="120"),
            sa.Column("cv_reference", sa.String(length=255), nullable=True),
            sa.Column("is_weak_area", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("rank_score", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("is_reserve_followup", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("followup_templates", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("question_bank_items")
