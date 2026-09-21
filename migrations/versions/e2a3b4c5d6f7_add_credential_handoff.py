"""add credential_handoff table

Revision ID: e2a3b4c5d6f7
Revises: d1f2e3a4b5c6
Create Date: 2026-09-21 00:00:00.000000

Le mot de passe généré ne transite plus par le cookie de session : il est
conservé côté serveur le temps d'une redirection, la session ne portant qu'un
jeton opaque. La ligne est supprimée dès l'affichage.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e2a3b4c5d6f7'
down_revision = 'd1f2e3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'credential_handoff',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('password', sa.String(length=64), nullable=False),
        sa.Column('regenerated', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('mail_sent', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_credential_handoff_token', 'credential_handoff', ['token'], unique=True)


def downgrade():
    op.drop_index('ix_credential_handoff_token', table_name='credential_handoff')
    op.drop_table('credential_handoff')
