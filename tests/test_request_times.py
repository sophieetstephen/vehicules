import pytest
from datetime import datetime
from app import app
from models import db, User, Reservation


def test_new_request_creates_correct_datetimes():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        user = User(
            name='Test User',
            first_name='Test',
            last_name='User',
            email='test@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        data = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'start_date': '2024-01-01',
            'start_slot': 'afternoon',
            'end_date': '2024-01-02',
            'end_slot': 'morning',
            'purpose': '',
            'carpool': '',
            'carpool_with': '',
            'notes': '',
        }
        client.post('/request/new', data=data, follow_redirects=True)
        r = Reservation.query.first()
        assert r.start_at == datetime(2024, 1, 1, 13, 0)
        assert r.end_at == datetime(2024, 1, 2, 12, 0)
        db.drop_all()


def test_new_request_without_end_date_uses_start_date_and_end_slot_time():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        user = User(
            name='Test User',
            first_name='Test',
            last_name='User',
            email='test@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        data = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'start_date': '2024-01-01',
            'start_slot': 'morning',
            'end_slot': 'afternoon',
            'purpose': '',
            'carpool': '',
            'carpool_with': '',
            'notes': '',
        }
        client.post('/request/new', data=data, follow_redirects=True)
        r = Reservation.query.first()
        assert r.start_at == datetime(2024, 1, 1, 8, 0)
        assert r.end_at == datetime(2024, 1, 1, 17, 0)
        db.drop_all()


def test_new_request_without_end_slot_defaults_to_start_slot():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        user = User(
            name='Test User',
            first_name='Test',
            last_name='User',
            email='test@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        data = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'start_date': '2024-01-01',
            'start_slot': 'afternoon',
            'purpose': '',
            'carpool': '',
            'carpool_with': '',
            'notes': '',
        }
        client.post('/request/new', data=data, follow_redirects=True)
        r = Reservation.query.first()
        assert r.start_at == datetime(2024, 1, 1, 13, 0)
        assert r.end_at == datetime(2024, 1, 1, 17, 0)
        db.drop_all()


def test_new_request_with_empty_end_slot_string_creates_reservation():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        user = User(
            name='Test User',
            first_name='Test',
            last_name='User',
            email='test@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        data = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'start_date': '2024-01-01',
            'start_slot': 'afternoon',
            'end_slot': '',
            'purpose': '',
            'carpool': '',
            'carpool_with': '',
            'notes': '',
        }
        resp = client.post('/request/new', data=data, follow_redirects=True)
        assert "La date de fin doit être postérieure à la date de début" not in resp.get_data(as_text=True)
        r = Reservation.query.first()
        assert r.start_at == datetime(2024, 1, 1, 13, 0)
        assert r.end_at == datetime(2024, 1, 1, 17, 0)
        db.drop_all()


def test_new_request_with_end_before_start_shows_error():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        user = User(
            name='Test User',
            first_name='Test',
            last_name='User',
            email='test@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        data = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'start_date': '2024-01-02',
            'start_slot': 'morning',
            'end_date': '2024-01-01',
            'end_slot': 'afternoon',
            'purpose': '',
            'carpool': '',
            'carpool_with': '',
            'notes': '',
        }
        resp = client.post('/request/new', data=data, follow_redirects=True)
        assert "La date de fin doit être postérieure à la date de début" in resp.get_data(as_text=True)
        assert Reservation.query.count() == 0
        db.drop_all()
