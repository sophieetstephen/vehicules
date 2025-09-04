import os
import sys
import pytest
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app, vehicles_availability
from models import db, User, Vehicle, Reservation, ReservationSegment
from utils import reservation_slot_label
from flask import render_template


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


def test_vehicle_availability_with_segments(app_ctx):
    v1 = Vehicle(code='V1', label='Vehicule 1')
    v2 = Vehicle(code='V2', label='Vehicule 2')
    db.session.add_all([v1, v2])
    u = create_user()
    r = Reservation(user_id=u.id, start_at=datetime(2024,1,1,8), end_at=datetime(2024,1,1,12), status='approved')
    db.session.add(r)
    db.session.commit()
    seg = ReservationSegment(reservation_id=r.id, vehicle_id=v1.id,
                             start_at=datetime(2024,1,1,8), end_at=datetime(2024,1,1,12))
    db.session.add(seg)
    db.session.commit()
    avail = dict((v.id, free) for v, free in vehicles_availability(datetime(2024,1,1,9), datetime(2024,1,1,10)))
    assert avail[v1.id] is False
    assert avail[v2.id] is True


def test_calendar_month_links_with_day_param(app_ctx):
    admin = create_user(role=User.ROLE_ADMIN)
    v1 = Vehicle(code='V1', label='Vehicule 1')
    v2 = Vehicle(code='V2', label='Vehicule 2')
    db.session.add_all([v1, v2])
    u = create_user()
    r = Reservation(vehicle_id=v1.id, user_id=u.id, start_at=datetime(2024,1,10,8), end_at=datetime(2024,1,10,12), status='approved')
    db.session.add(r)
    db.session.commit()
    with app.test_request_context('/calendar/month'):
        html = render_template('calendar_month.html', vehicles=[v1, v2], reservations=[r], segments=[], start=datetime(2024,1,1), end=datetime(2024,2,1), user=admin, timedelta=timedelta, slot_label=reservation_slot_label)
    assert f"/admin/manage/{r.id}?day=2024-01-10" in html
    assert 'name="vehicle_id"' not in html


def test_segment_day_creates_segment(app_ctx):
    admin = create_user(role=User.ROLE_ADMIN)
    user = create_user()
    v1 = Vehicle(code='V1', label='Vehicule 1')
    v2 = Vehicle(code='V2', label='Vehicule 2')
    db.session.add_all([v1, v2])
    db.session.commit()
    r = Reservation(vehicle_id=v1.id, user_id=user.id,
                    start_at=datetime(2024,1,1,8), end_at=datetime(2024,1,3,16), status='approved')
    db.session.add(r)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['uid'] = admin.id
    data = {
        'action': 'segment_day',
        'vehicle_id': str(v2.id),
    }
    client.post(f'/admin/manage/{r.id}?day=2024-01-02', data=data)
    segs = ReservationSegment.query.filter_by(reservation_id=r.id).order_by(ReservationSegment.start_at).all()
    assert len(segs) == 3
    seg_before, seg_day, seg_after = segs
    assert seg_before.vehicle_id == v1.id
    assert seg_before.start_at == datetime(2024,1,1,8)
    assert seg_before.end_at == datetime(2024,1,1,23,59,59,999999)
    assert seg_day.vehicle_id == v2.id
    assert seg_day.start_at.date() == datetime(2024,1,2).date()
    assert seg_day.end_at.date() == datetime(2024,1,2).date()
    assert seg_after.vehicle_id == v1.id
    assert seg_after.start_at == datetime(2024,1,3)
    assert seg_after.end_at == datetime(2024,1,3,16)
    assert Reservation.query.get(r.id).vehicle_id is None
