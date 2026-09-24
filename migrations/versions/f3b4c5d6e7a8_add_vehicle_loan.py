"""Vehicules a usage reserve et prets temporaires

Revision ID: f3b4c5d6e7a8
Revises: e2a3b4c5d6f7
Create Date: 2026-09-25

Les vehicules du chef et de l'adjoint etaient declares indisponibles
jusqu'a nouvel ordre, comme une panne. « reserved_for » distingue l'usage
reserve, et vehicle_loan enregistre les periodes ou ils sont pretes.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f3b4c5d6e7a8'
down_revision = 'e2a3b4c5d6f7'
branch_labels = None
depends_on = None


def upgrade():
    # Ajout de colonne : SQLite le fait sans reconstruire la table.
    op.add_column('vehicle', sa.Column('reserved_for', sa.String(length=80), nullable=True))
    op.create_table(
        'vehicle_loan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vehicle_id', sa.Integer(), nullable=False),
        sa.Column('start_at', sa.DateTime(), nullable=False),
        sa.Column('end_at', sa.DateTime(), nullable=False),
        sa.Column('reason', sa.String(length=200), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id']),
        sa.ForeignKeyConstraint(['created_by'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('vehicle_loan')
    with op.batch_alter_table('vehicle') as batch_op:
        batch_op.drop_column('reserved_for')
