import os
import sys
from datetime import datetime, timedelta

from flask import render_template

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app
from models import User, Vehicle, Reservation
from utils import reservation_slot_label


def test_calendar_month_displays_purpose():
    start = datetime(2024, 3, 1)
    end = datetime(2024, 4, 1)
    user = User(
        name='Test User',
        first_name='Test',
        last_name='User',
        email='test@example.com',
        role=User.ROLE_USER,
        password_hash='x',
    )
    vehicle = Vehicle(id=1, code='V1', label='Vehicule 1')
    reservation = Reservation(
        id=1,
        vehicle_id=vehicle.id,
        user=user,
        user_id=user.id,
        vehicle=vehicle,
        start_at=datetime(2024, 3, 10, 8),
        end_at=datetime(2024, 3, 10, 12),
        purpose='Mission',
    )
    with app.test_request_context('/calendar/month'):
        html = render_template(
            'calendar_month.html',
            vehicles=[vehicle],
            reservations=[reservation],
            segments=[],
            start=start,
            end=end,
            user=user,
            timedelta=timedelta,
            slot_label=reservation_slot_label,
        )
    assert 'Mission' in html.split('<strong>V1</strong>')[1]
