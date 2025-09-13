import os
import sys
import pytest
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app
from models import db, User, Vehicle, Reservation, ReservationSegment


@pytest.fixture
def app_ctx():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.drop_all()


def create_user(role=User.ROLE_USER):
    u = User(
        name='User',
        first_name='U',
        last_name='Ser',
        email=f'user{role}@example.com',
        role=role,
        password_hash='x',
        status='active',
    )
    db.session.add(u)
    db.session.commit()
    return u


def test_delete_reservation_removes_segments(app_ctx):
    admin = create_user(role=User.ROLE_ADMIN)
    user = create_user()
    v1 = Vehicle(code='V1', label='Vehicule 1')
    v2 = Vehicle(code='V2', label='Vehicule 2')
    db.session.add_all([v1, v2])
    db.session.commit()
    r = Reservation(
        vehicle_id=v1.id,
        user_id=user.id,
        start_at=datetime(2024, 1, 1, 8),
        end_at=datetime(2024, 1, 1, 12),
        status='approved',
    )
    db.session.add(r)
    db.session.commit()
    seg1 = ReservationSegment(
        reservation_id=r.id,
        vehicle_id=v1.id,
        start_at=datetime(2024, 1, 1, 8),
        end_at=datetime(2024, 1, 1, 10),
    )
    seg2 = ReservationSegment(
        reservation_id=r.id,
        vehicle_id=v2.id,
        start_at=datetime(2024, 1, 1, 10),
        end_at=datetime(2024, 1, 1, 12),
    )
    db.session.add_all([seg1, seg2])
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['uid'] = admin.id
    data = {'action': 'delete'}
    client.post(f'/admin/manage/{r.id}', data=data)

    assert Reservation.query.get(r.id) is None
    assert ReservationSegment.query.filter_by(reservation_id=r.id).count() == 0
