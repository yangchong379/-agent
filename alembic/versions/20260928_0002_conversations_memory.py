"""Add adaptive interview turns, career conversations and managed memory."""

import sqlalchemy as sa
from alembic import op

from app.db import models  # noqa: F401
from app.db.base import Base


revision = "20260928_0002"
down_revision = "20260924_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("interview_runs")}
    if "max_turns" not in columns:
        op.add_column(
            "interview_runs",
            sa.Column("max_turns", sa.Integer(), nullable=False, server_default="2"),
        )
    for table_name in ("conversations", "conversation_messages", "user_memories"):
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ("user_memories", "conversation_messages", "conversations"):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
    columns = {item["name"] for item in sa.inspect(bind).get_columns("interview_runs")}
    if "max_turns" in columns:
        op.drop_column("interview_runs", "max_turns")
