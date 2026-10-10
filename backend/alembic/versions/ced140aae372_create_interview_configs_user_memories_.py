"""create interview_configs user_memories asked_questions

Revision ID: ced140aae372
Revises: d12eec69dc55
Create Date: 2026-10-10 17:56:15.788229

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'ced140aae372'
down_revision: Union[str, Sequence[str], None] = 'd12eec69dc55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = inspector.get_table_names()

    if "interview_configs" not in existing_tables:
        op.create_table(
            "interview_configs",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("round_type", sa.String(length=50), nullable=False),
            sa.Column("difficulty", sa.String(length=50), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=False),
            sa.Column("language", sa.String(length=50), nullable=False, server_default="English"),
            sa.Column("mode", sa.String(length=50), nullable=False, server_default="normal"),
            sa.Column("focus_topics", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if "user_memories" not in existing_tables:
        op.create_table(
            "user_memories",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True),
            sa.Column("topic_scores", sa.JSON(), nullable=False),
            sa.Column("weak_topics", sa.JSON(), nullable=False),
            sa.Column("session_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_session_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "asked_questions" not in existing_tables:
        op.create_table(
            "asked_questions",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("question_hash", sa.String(length=64), nullable=False, index=True),
            sa.Column("topic", sa.String(length=100), nullable=False, index=True),
            sa.Column("question_text", sa.Text(), nullable=True),
            sa.Column("asked_at", sa.DateTime(), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("asked_questions")
    op.drop_table("user_memories")
    op.drop_table("interview_configs")
