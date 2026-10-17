"""create_phase4_tables

Revision ID: a1b2c3d4e5f6
Revises: 9c112ebd5391
Create Date: 2026-09-24 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9c112ebd5391'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create recommendations and reflections tables."""
    op.create_table(
        'recommendations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('recommendation_type', sa.String(length=20), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=True),
        sa.Column('topic', sa.String(length=100), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('target_rating_min', sa.Integer(), nullable=True),
        sa.Column('target_rating_max', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['problem_id'], ['problems.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_recommendations_user_id', 'recommendations', ['user_id'])
    op.create_index('ix_recommendations_status', 'recommendations', ['status'])

    op.create_table(
        'reflections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column(
            'metrics',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False,
        ),
        sa.Column(
            'generated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'date', name='uq_reflection_user_date'),
    )
    op.create_index('ix_reflections_user_id', 'reflections', ['user_id'])


def downgrade() -> None:
    """Drop Phase 4 tables."""
    op.drop_index('ix_reflections_user_id', table_name='reflections')
    op.drop_table('reflections')
    op.drop_index('ix_recommendations_status', table_name='recommendations')
    op.drop_index('ix_recommendations_user_id', table_name='recommendations')
    op.drop_table('recommendations')
