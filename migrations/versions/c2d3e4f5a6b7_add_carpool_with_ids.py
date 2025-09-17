"""add carpool_with_ids to reservation

Revision ID: c2d3e4f5a6b7
Revises: b9f8d1e7e3c9
Create Date: 2024-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = 'b9f8d1e7e3c9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reservation', sa.Column('carpool_with_ids', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('reservation', 'carpool_with_ids')
