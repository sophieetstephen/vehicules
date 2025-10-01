import os
import sys
from datetime import datetime, timedelta

from flask import render_template
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app
from models import Vehicle, Reservation, User
from utils import reservation_slot_label


def test_same_day_reservations_have_distinct_slots():
    start = datetime(2024, 1, 1)
    end = datetime(2024, 2, 1)
    v = Vehicle(id=1, code='V1', label='Vehicule 1')
    viewer = User(name='Viewer', first_name='View', last_name='Er', email='viewer@example.com', role=User.ROLE_USER, password_hash='x')
    u1 = User(name='Alice', first_name='Alice', last_name='A', email='a@example.com', role=User.ROLE_USER, password_hash='x')
    u2 = User(name='Bob', first_name='Bob', last_name='B', email='b@example.com', role=User.ROLE_USER, password_hash='x')
    r1 = Reservation(vehicle_id=1, user_id=1, start_at=datetime(2024, 1, 10, 8, 0), end_at=datetime(2024, 1, 10, 12, 0))
    r1.user = u1
    r2 = Reservation(vehicle_id=1, user_id=2, start_at=datetime(2024, 1, 10, 13, 0), end_at=datetime(2024, 1, 10, 17, 0))
    r2.user = u2
    with app.test_request_context('/calendar/month'):
        html = render_template(
            'calendar_month.html',
            vehicles=[v],
            reservations=[r1, r2],
            start=start,
            end=end,
            user=viewer,
            timedelta=timedelta,
            slot_label=reservation_slot_label,
        )
        pdf_html = render_template(
            'pdf_month.html',
            vehicles=[v],
            reservations=[r1, r2],
            start=start,
            end=end,
            slot_label=reservation_slot_label,
            timedelta=timedelta,
        )
    assert 'Alice (Matin)' in html
    assert 'Bob (Après-midi)' in html
    assert 'Matin' in pdf_html
    assert 'Après-midi' in pdf_html
    assert 'rowspan="2"' in pdf_html
    assert 'vehicle-row--second' in pdf_html
    assert 'class="filler-cell"' in pdf_html


def test_partial_afternoon_reservation_is_labelled_afternoon():
    reservation = Reservation(
        vehicle_id=1,
        user_id=1,
        start_at=datetime(2024, 1, 10, 13, 0),
        end_at=datetime(2024, 1, 10, 16, 59),
    )
    day = datetime(2024, 1, 10)
    assert reservation_slot_label(reservation, day) == "Après-midi"
