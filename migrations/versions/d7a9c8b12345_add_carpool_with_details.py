"""add carpool_with_details to reservation

Revision ID: d7a9c8b12345
Revises: c2d3e4f5a6b7
Create Date: 2024-08-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7a9c8b12345'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('reservation', sa.Column('carpool_with_details', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('reservation', 'carpool_with_details')
