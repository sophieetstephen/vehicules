import os
import sys
from datetime import datetime, timedelta

import pytest
from flask import render_template

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app
from models import User


@pytest.mark.parametrize('role', [User.ROLE_USER, User.ROLE_ADMIN, User.ROLE_SUPERADMIN])
def test_calendar_links_visible(role):
    start = datetime(2024, 3, 1)
    end = datetime(2024, 4, 1)
    with app.test_request_context('/calendar/month'):
        user = User(name='Test', email='test@example.com', role=role, password_hash='x')
        html = render_template(
            'calendar_month.html',
            vehicles=[],
            reservations=[],
            start=start,
            end=end,
            user=user,
            timedelta=timedelta,
        )
    assert '?y=2024&amp;m=2' in html
    assert '?y=2024&amp;m=4' in html


def test_calendar_month_params_interpreted():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    from models import db
    with app.app_context():
        db.create_all()
        user = User(name='User', email='user@example.com', role=User.ROLE_USER, password_hash='x')
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        resp = client.get('/calendar/month?y=2023&m=12')
        html = resp.data.decode('utf-8')
        assert '?y=2023&amp;m=11' in html
        assert '?y=2024&amp;m=1' in html
        db.drop_all()
