import pytest
from app import app
from models import db, User, Reservation


def test_pending_user_cannot_create_request():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        user = User(
            name='Pending User',
            first_name='Pending',
            last_name='User',
            email='pending@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='pending',
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
            'end_date': '2024-01-01',
            'end_slot': 'morning',
            'purpose': '',
            'carpool': '',
            'carpool_with': '',
            'notes': '',
        }
        resp = client.post('/request/new', data=data)
        assert resp.status_code in (302, 403)
        assert Reservation.query.count() == 0
        db.drop_all()
