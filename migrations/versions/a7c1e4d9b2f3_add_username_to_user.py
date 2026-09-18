"""add username (login identifier) to user

Revision ID: a7c1e4d9b2f3
Revises: fc2a1d4e5b67
Create Date: 2026-09-18 00:00:00.000000

L'adresse e-mail ne sert plus d'identifiant de connexion. Chaque compte reçoit
un identifiant "nom + initiale du prénom" (ex: dupontj). Les comptes existants
sont migrés automatiquement et les identifiants générés sont affichés dans la
sortie de ``flask db upgrade``.
"""

import os
import sys

from alembic import op
import sqlalchemy as sa

# Rendre utils.py importable quel que soit le répertoire courant.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils import build_username_base, make_unique_username  # noqa: E402

# revision identifiers, used by Alembic.
revision = 'a7c1e4d9b2f3'
down_revision = 'fc2a1d4e5b67'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('username', sa.String(length=60), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            'SELECT id, first_name, last_name, name, email FROM "user" ORDER BY id'
        )
    ).fetchall()
    taken = set()
    print("\n=== Identifiants de connexion générés ===")
    for row in rows:
        base = build_username_base(
            first_name=row.first_name,
            last_name=row.last_name,
            name=row.name,
            email=row.email,
        )
        username = make_unique_username(base, lambda c: c in taken)
        taken.add(username)
        bind.execute(
            sa.text('UPDATE "user" SET username = :username WHERE id = :id'),
            {"username": username, "id": row.id},
        )
        print(f"  {row.email:40} -> {username}")
    print("=========================================\n")

    op.create_index('ix_user_username', 'user', ['username'], unique=True)


def downgrade():
    op.drop_index('ix_user_username', table_name='user')
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('username')
