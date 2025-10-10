"""add archived_at to reservation

Revision ID: fc2a1d4e5b67
Revises: e9ea29198235
Create Date: 2024-05-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fc2a1d4e5b67'
down_revision = 'e9ea29198235'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reservation', sa.Column('archived_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('reservation', 'archived_at')
