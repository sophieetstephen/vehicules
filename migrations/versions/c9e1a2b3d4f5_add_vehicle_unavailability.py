"""add vehicle_unavailability table

Revision ID: c9e1a2b3d4f5
Revises: b8d2f6a1c4e7
Create Date: 2026-09-18 00:00:00.000000

Permet de déclarer un véhicule indisponible (panne, entretien, carrosserie…)
sur une période, éventuellement sans date de fin.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c9e1a2b3d4f5'
down_revision = 'b8d2f6a1c4e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vehicle_unavailability',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicle.id'), nullable=False),
        sa.Column('start_at', sa.DateTime(), nullable=False),
        sa.Column('end_at', sa.DateTime(), nullable=True),
        sa.Column('category', sa.String(length=30), nullable=False, server_default='mecanique'),
        sa.Column('details', sa.String(length=200), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_vehicle_unavailability_vehicle_id', 'vehicle_unavailability', ['vehicle_id']
    )


def downgrade():
    op.drop_index('ix_vehicle_unavailability_vehicle_id', table_name='vehicle_unavailability')
    op.drop_table('vehicle_unavailability')
