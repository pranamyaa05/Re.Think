"""add external_id to users

Revision ID: 000000000000
Revises: e1f2a3b4c5d6
Create Date: None
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000000'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('external_id', sa.String(255), unique=True, nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'external_id')
