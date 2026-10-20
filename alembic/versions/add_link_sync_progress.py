"""Add sync progress columns to platform_links.

Revision ID: add_link_sync_progress
Revises: b7c8d9e0f1a2
Create Date: 2026-10-20

Extends the platform link row with the last sync's progress counts so the
GET /platforms/{id}/status endpoint can report honest progress (fetched vs
newly inserted) and whether per-submission data is available for a link
(LeetCode links without a session cookie cannot provide submissions).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_link_sync_progress"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "platform_links",
        sa.Column("submissions_fetched", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "platform_links",
        sa.Column("submissions_inserted", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "platform_links",
        sa.Column("contests_fetched", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "platform_links",
        sa.Column("contests_inserted", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "platform_links",
        sa.Column("problems_upserted", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "platform_links",
        sa.Column(
            "submissions_available",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("platform_links", "submissions_available")
    op.drop_column("platform_links", "problems_upserted")
    op.drop_column("platform_links", "contests_inserted")
    op.drop_column("platform_links", "contests_fetched")
    op.drop_column("platform_links", "submissions_inserted")
    op.drop_column("platform_links", "submissions_fetched")
