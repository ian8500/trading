"""store serialised backtest result payload

Revision ID: 95be8f13c7b2
Revises: 2beac83591a7
Create Date: 2026-08-19 23:48:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "95be8f13c7b2"  # pragma: allowlist secret -- Alembic revision identifier
down_revision: str | None = "2beac83591a7"  # pragma: allowlist secret -- revision identifier
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "backtests",
        sa.Column("result_payload", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("backtests", "result_payload")
