"""merge external_id head with phase5 problem platform id head

Revision ID: b7c8d9e0f1a2
Revises: 000000000000, f1a2b3c4d5e6
Create Date: 2026-10-20

The external_id migration was authored against e1f2a3b4c5d6 while the real
head had already advanced to f1a2b3c4d5e6, producing two heads. This merge
revision restores a single linear head without rewriting either migration.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = ("000000000000", "f1a2b3c4d5e6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
