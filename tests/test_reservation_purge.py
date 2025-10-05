import pytest
from datetime import datetime, timedelta
from app import app, purge_expired_requests
from models import db, User, Reservation


def test_purge_expired_pending_reservations():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

        user = User(
            name='User',
            first_name='Foo',
            last_name='Bar',
            email='u@example.com',
            role=User.ROLE_USER,
            password_hash='x'
        )
        db.session.add(user)
        db.session.commit()

        old_end = datetime.utcnow() - timedelta(days=3)
        new_end = datetime.utcnow() - timedelta(days=1)
        old_res = Reservation(
            user_id=user.id,
            start_at=old_end - timedelta(hours=1),
            end_at=old_end,
            status='pending'
        )
        fresh_res = Reservation(
            user_id=user.id,
            start_at=new_end - timedelta(hours=1),
            end_at=new_end,
            status='pending'
        )
        db.session.add_all([old_res, fresh_res])
        db.session.commit()

        purge_expired_requests()

        assert Reservation.query.count() == 1
        assert Reservation.query.first().id == fresh_res.id
        db.drop_all()


def test_purge_expired_non_pending_reservations():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

        user = User(
            name='User',
            first_name='Foo',
            last_name='Bar',
            email='u2@example.com',
            role=User.ROLE_USER,
            password_hash='x'
        )
        db.session.add(user)
        db.session.commit()

        now = datetime.utcnow()
        very_old_end = now - timedelta(days=8)
        recent_end = now - timedelta(days=6)

        old_approved = Reservation(
            user_id=user.id,
            start_at=very_old_end - timedelta(hours=2),
            end_at=very_old_end,
            status='approved'
        )
        old_rejected = Reservation(
            user_id=user.id,
            start_at=very_old_end - timedelta(hours=3),
            end_at=very_old_end - timedelta(minutes=30),
            status='rejected'
        )
        recent_approved = Reservation(
            user_id=user.id,
            start_at=recent_end - timedelta(hours=1),
            end_at=recent_end,
            status='approved'
        )
        recent_rejected = Reservation(
            user_id=user.id,
            start_at=recent_end - timedelta(hours=1, minutes=30),
            end_at=recent_end - timedelta(minutes=10),
            status='rejected'
        )
        recent_pending = Reservation(
            user_id=user.id,
            start_at=now - timedelta(hours=2),
            end_at=now - timedelta(hours=1),
            status='pending'
        )

        db.session.add_all([
            old_approved,
            old_rejected,
            recent_approved,
            recent_rejected,
            recent_pending,
        ])
        db.session.commit()

        deleted = purge_expired_requests()

        remaining_ids = {res.id for res in Reservation.query.all()}
        assert deleted == 2
        assert remaining_ids == {
            recent_approved.id,
            recent_rejected.id,
            recent_pending.id,
        }

        db.drop_all()
