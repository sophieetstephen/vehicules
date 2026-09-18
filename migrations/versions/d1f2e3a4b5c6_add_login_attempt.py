"""add login_attempt table (limitation des tentatives de connexion)

Revision ID: d1f2e3a4b5c6
Revises: c9e1a2b3d4f5
Create Date: 2026-09-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd1f2e3a4b5c6'
down_revision = 'c9e1a2b3d4f5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'login_attempt',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(length=60), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_login_attempt_username', 'login_attempt', ['username'])
    op.create_index('ix_login_attempt_ip', 'login_attempt', ['ip'])
    op.create_index('ix_login_attempt_created_at', 'login_attempt', ['created_at'])


def downgrade():
    op.drop_index('ix_login_attempt_created_at', table_name='login_attempt')
    op.drop_index('ix_login_attempt_ip', table_name='login_attempt')
    op.drop_index('ix_login_attempt_username', table_name='login_attempt')
    op.drop_table('login_attempt')
