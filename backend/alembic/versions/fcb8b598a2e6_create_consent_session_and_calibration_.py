"""create consent session and calibration tables

Revision ID: fcb8b598a2e6
Revises: bf5ad75e9047
Create Date: 2026-10-11 16:04:44.940375

"""
from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'fcb8b598a2e6'
down_revision: Union[str, Sequence[str], None] = 'bf5ad75e9047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = inspector.get_table_names()

    if "user_consents" not in existing_tables:
        op.create_table(
            "user_consents",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("version", sa.String(length=50), nullable=False, server_default="v1.0"),
            sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("can_delete", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("accepted_at", sa.DateTime(), nullable=False),
        )

    if "interview_sessions" not in existing_tables:
        op.create_table(
            "interview_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_configs.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="created"),
            sa.Column("session_token", sa.String(length=255), unique=True, nullable=False, index=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if "session_calibrations" not in existing_tables:
        op.create_table(
            "session_calibrations",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True, nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("face_baseline", sa.JSON(), nullable=False),
            sa.Column("voice_baseline", sa.JSON(), nullable=False),
            sa.Column("background_noise_level_db", sa.Float(), nullable=False, server_default="-50.0"),
            sa.Column("calibration_text", sa.String(length=500), nullable=True),
            sa.Column("calibrated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("session_calibrations")
    op.drop_table("interview_sessions")
    op.drop_table("user_consents")
