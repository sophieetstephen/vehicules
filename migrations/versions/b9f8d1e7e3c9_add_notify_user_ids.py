"""add notify_user_ids to notification settings

Revision ID: b9f8d1e7e3c9
Revises: 3b1436a41c1b
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b9f8d1e7e3c9'
down_revision = '3b1436a41c1b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('notification_settings', sa.Column('notify_user_ids', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('notification_settings', 'notify_user_ids')
