"""merge username (login identifier) and archived branches

Revision ID: b8d2f6a1c4e7
Revises: 1d278201d3ef, a7c1e4d9b2f3
Create Date: 2026-09-18 00:00:00.000000

Réunit les deux têtes de migration pour que ``flask db upgrade`` fonctionne
quel que soit l'état de la base (ancienne installation ou installation
récente).
"""

# revision identifiers, used by Alembic.
revision = 'b8d2f6a1c4e7'
down_revision = ('1d278201d3ef', 'a7c1e4d9b2f3')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
