"""add notification settings

Revision ID: 3b1436a41c1b
Revises: 80a34f7228b0
Create Date: 2025-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3b1436a41c1b'
down_revision = '80a34f7228b0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notification_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('notify_superadmin', sa.Boolean(), nullable=True),
        sa.Column('notify_admin', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('notification_settings')
