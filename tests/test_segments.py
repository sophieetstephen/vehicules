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


def test_calendar_month_segment_link(app_ctx):
    admin = create_user(role=User.ROLE_ADMIN)
    v1 = Vehicle(code='V1', label='Vehicule 1')
    v2 = Vehicle(code='V2', label='Vehicule 2')
    db.session.add_all([v1, v2])
    u = create_user()
    r = Reservation(user_id=u.id, start_at=datetime(2024,1,10,8), end_at=datetime(2024,1,10,12), status='approved')
    db.session.add(r)
    db.session.commit()
    seg = ReservationSegment(reservation_id=r.id, vehicle_id=v1.id,
                             start_at=datetime(2024,1,10,8), end_at=datetime(2024,1,10,12))
    db.session.add(seg)
    db.session.commit()
    with app.test_request_context('/calendar/month'):
        html = render_template('calendar_month.html', vehicles=[v1, v2], reservations=[], segments=[seg], start=datetime(2024,1,1), end=datetime(2024,2,1), user=admin, timedelta=timedelta, slot_label=reservation_slot_label)
    assert f"/admin/manage/segment/{seg.id}" in html


def test_calendar_month_partially_segmented_shows_remaining_days(app_ctx):
    admin = create_user(role=User.ROLE_ADMIN)
    user = create_user()
    v1 = Vehicle(code='V1', label='Vehicule 1')
    v2 = Vehicle(code='V2', label='Vehicule 2')
    db.session.add_all([v1, v2])
    db.session.commit()
    r = Reservation(
        vehicle_id=v1.id,
        user_id=user.id,
        start_at=datetime(2024, 1, 10, 8),
        end_at=datetime(2024, 1, 12, 16),
        status='approved',
    )
    db.session.add(r)
    db.session.commit()
    seg = ReservationSegment(
        reservation_id=r.id,
        vehicle_id=v2.id,
        start_at=datetime(2024, 1, 11, 8),
        end_at=datetime(2024, 1, 11, 16),
    )
    db.session.add(seg)
    db.session.commit()
    with app.test_request_context('/calendar/month'):
        html = render_template(
            'calendar_month.html',
            vehicles=[v1, v2],
            reservations=[r],
            segments=[seg],
            start=datetime(2024, 1, 1),
            end=datetime(2024, 2, 1),
            user=admin,
            timedelta=timedelta,
            slot_label=reservation_slot_label,
        )
    assert f"/admin/manage/{r.id}?day=2024-01-10" in html
    assert f"/admin/manage/{r.id}?day=2024-01-12" in html
    assert f"/admin/manage/{r.id}?day=2024-01-11" not in html
    assert f"/admin/manage/segment/{seg.id}" in html


def test_segment_day_preserves_other_days(app_ctx):
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
        end_at=datetime(2024, 1, 3, 16),
        status='approved',
    )
    db.session.add(r)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['uid'] = admin.id
    data = {'action': 'segment_day', 'vehicle_id': str(v2.id)}
    client.post(f'/admin/manage/{r.id}?day=2024-01-02', data=data)
    segments = (
        ReservationSegment.query.filter_by(reservation_id=r.id)
        .order_by(ReservationSegment.start_at)
        .all()
    )
    assert len(segments) == 3
    seg_day1, seg_day2, seg_day3 = segments
    assert seg_day1.vehicle_id == v1.id
    assert seg_day2.vehicle_id == v2.id
    assert seg_day3.vehicle_id == v1.id
    assert seg_day1.start_at.date() == datetime(2024, 1, 1).date()
    assert seg_day3.start_at.date() == datetime(2024, 1, 3).date()


def test_segment_day_keeps_all_other_days(app_ctx):
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
        end_at=datetime(2024, 1, 4, 16),
        status='approved',
    )
    db.session.add(r)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['uid'] = admin.id
    data = {'action': 'segment_day', 'vehicle_id': str(v2.id)}
    client.post(f'/admin/manage/{r.id}?day=2024-01-02', data=data)
    segments = (
        ReservationSegment.query.filter_by(reservation_id=r.id)
        .order_by(ReservationSegment.start_at)
        .all()
    )
    assert len(segments) == 4
    seg_day1, seg_day2, seg_day3, seg_day4 = segments
    assert seg_day1.start_at.date() == datetime(2024, 1, 1).date()
    assert seg_day2.start_at.date() == datetime(2024, 1, 2).date()
    assert seg_day3.start_at.date() == datetime(2024, 1, 3).date()
    assert seg_day4.start_at.date() == datetime(2024, 1, 4).date()
    assert seg_day1.vehicle_id == v1.id
    assert seg_day2.vehicle_id == v2.id
    assert seg_day3.vehicle_id == v1.id
    assert seg_day4.vehicle_id == v1.id


def test_segment_day_can_be_repeated_and_managed(app_ctx):
    admin = create_user(role=User.ROLE_ADMIN)
    user = create_user()
    v1 = Vehicle(code='V1', label='Vehicule 1')
    v2 = Vehicle(code='V2', label='Vehicule 2')
    v3 = Vehicle(code='V3', label='Vehicule 3')
    db.session.add_all([v1, v2, v3])
    db.session.commit()
    r = Reservation(vehicle_id=v1.id, user_id=user.id,
                    start_at=datetime(2024,1,1,8), end_at=datetime(2024,1,3,16), status='approved')
    db.session.add(r)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['uid'] = admin.id
    # segment day 2 to v2
    data = {'action': 'segment_day', 'vehicle_id': str(v2.id)}
    client.post(f'/admin/manage/{r.id}?day=2024-01-02', data=data)
    segs = ReservationSegment.query.filter_by(reservation_id=r.id).order_by(ReservationSegment.start_at).all()
    assert len(segs) == 3
    seg_day1, seg_day2, seg_day3 = segs
    assert seg_day1.vehicle_id == v1.id
    assert seg_day2.vehicle_id == v2.id
    assert seg_day3.vehicle_id == v1.id
    # segment day 3 to v3 (update existing segment)
    data = {'action': 'segment_day', 'vehicle_id': str(v3.id)}
    client.post(f'/admin/manage/{r.id}?day=2024-01-03', data=data)
    segs = ReservationSegment.query.filter_by(reservation_id=r.id).order_by(ReservationSegment.start_at).all()
    assert len(segs) == 3
    seg_day1, seg_day2, seg_day3 = segs
    assert seg_day2.start_at.date() == datetime(2024,1,2).date()
    assert seg_day3.start_at.date() == datetime(2024,1,3).date()
    assert seg_day3.vehicle_id == v3.id
    # update second segment to v1
    data = {'action': 'update', 'vehicle_id': str(v1.id)}
    client.post(f'/admin/manage/segment/{seg_day2.id}', data=data)
    assert ReservationSegment.query.get(seg_day2.id).vehicle_id == v1.id
    # delete third segment
    data = {'action': 'delete'}
    client.post(f'/admin/manage/segment/{seg_day3.id}', data=data)
    assert ReservationSegment.query.filter_by(reservation_id=r.id).count() == 2
    # segment day 3 again
    data = {'action': 'segment_day', 'vehicle_id': str(v3.id)}
    client.post(f'/admin/manage/{r.id}?day=2024-01-03', data=data)
    assert ReservationSegment.query.filter_by(reservation_id=r.id).count() == 3


def test_segment_update_sends_mail(app_ctx, monkeypatch):
    admin = create_user(role=User.ROLE_ADMIN)
    user = create_user()
    v1 = Vehicle(code="V1", label="Vehicule 1")
    v2 = Vehicle(code="V2", label="Vehicule 2")
    db.session.add_all([v1, v2])
    db.session.commit()
    r = Reservation(
        user_id=user.id,
        start_at=datetime(2024, 1, 1, 8),
        end_at=datetime(2024, 1, 1, 12),
        status="approved",
    )
    db.session.add(r)
    db.session.commit()
    seg = ReservationSegment(
        reservation_id=r.id,
        vehicle_id=v1.id,
        start_at=datetime(2024, 1, 1, 8),
        end_at=datetime(2024, 1, 1, 12),
    )
    db.session.add(seg)
    db.session.commit()

    called = {}

    def fake_send_mail(subject, body, to_addr):
        called["args"] = (subject, body, to_addr)
        return True, "sent"

    monkeypatch.setattr("app.send_mail_msmtp", fake_send_mail)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["uid"] = admin.id
    data = {"action": "update", "vehicle_id": str(v2.id)}
    client.post(f"/admin/manage/segment/{seg.id}", data=data)

    assert ReservationSegment.query.get(seg.id).vehicle_id == v2.id
    subject, body, to_addr = called["args"]
    assert subject == "Modification de votre réservation"
    assert to_addr == user.email
    assert "Vehicule 1" in body
    assert "Vehicule 2" in body
    assert "01/01/2024 08:00" in body
    assert "01/01/2024 12:00" in body


def test_calendar_links_for_multiple_day_segments(app_ctx):
    admin = create_user(role=User.ROLE_ADMIN)
    user = create_user()
    v1 = Vehicle(code='V1', label='Vehicule 1')
    v2 = Vehicle(code='V2', label='Vehicule 2')
    v3 = Vehicle(code='V3', label='Vehicule 3')
    db.session.add_all([v1, v2, v3])
    db.session.commit()
    r = Reservation(
        vehicle_id=v1.id,
        user_id=user.id,
        start_at=datetime(2024, 1, 1, 8),
        end_at=datetime(2024, 1, 3, 16),
        status='approved',
    )
    db.session.add(r)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['uid'] = admin.id
    # segment day 2 to v2
    data = {'action': 'segment_day', 'vehicle_id': str(v2.id)}
    client.post(f'/admin/manage/{r.id}?day=2024-01-02', data=data)
    # segment day 3 to v3
    data = {'action': 'segment_day', 'vehicle_id': str(v3.id)}
    client.post(f'/admin/manage/{r.id}?day=2024-01-03', data=data)
    segments = (
        ReservationSegment.query.filter_by(reservation_id=r.id)
        .order_by(ReservationSegment.start_at)
        .all()
    )
    assert len(segments) == 3
    seg_day1, seg_day2, seg_day3 = segments
    assert seg_day1.start_at.date() == datetime(2024, 1, 1).date()
    assert seg_day1.vehicle_id == v1.id
    assert seg_day2.start_at.date() == datetime(2024, 1, 2).date()
    assert seg_day2.vehicle_id == v2.id
    assert seg_day3.start_at.date() == datetime(2024, 1, 3).date()
    assert seg_day3.vehicle_id == v3.id
    # calendar should show edit links for each segment
    with app.test_request_context('/calendar/month'):
        html = render_template(
            'calendar_month.html',
            vehicles=[v1, v2, v3],
            reservations=[r],
            segments=segments,
            start=datetime(2024, 1, 1),
            end=datetime(2024, 2, 1),
            user=admin,
            timedelta=timedelta,
            slot_label=reservation_slot_label,
        )
    for seg in segments:
        assert f"/admin/manage/segment/{seg.id}" in html
