"""add_phase5a_columns

Revision ID: e1f2a3b4c5d6
Revises: a1b2c3d4e5f6
Create Date: 2026-10-04 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('problems', sa.Column('difficulty_label', sa.String(length=20), nullable=True))
    op.add_column('platform_links', sa.Column('auth_token', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('platform_links', 'auth_token')
    op.drop_column('problems', 'difficulty_label')
