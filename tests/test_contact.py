import pytest
from app import app
from models import db, User, NotificationSettings


def setup_users():
    admin = User(
        name='Admin User',
        first_name='Admin',
        last_name='User',
        email='admin@example.com',
        role=User.ROLE_ADMIN,
        password_hash='x',
        status='active',
    )
    user = User(
        name='Normal User',
        first_name='Normal',
        last_name='User',
        email='user@example.com',
        role=User.ROLE_USER,
        password_hash='x',
        status='active',
    )
    return admin, user


def test_contact_page_renders():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        admin, user = setup_users()
        db.session.add_all([admin, user])
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        resp = client.get('/contact')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'class="card"' in html
        assert 'class="form-label"' in html
        db.drop_all()


def test_contact_sends_emails(monkeypatch):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        admin, user = setup_users()
        db.session.add_all([admin, user])
        db.session.commit()
        settings = NotificationSettings(notify_user_ids=[admin.id])
        db.session.add(settings)
        db.session.commit()

        calls = []

        def fake_send_mail(subject, body, recipients):
            calls.append((subject, body, recipients))

        monkeypatch.setattr('app.send_mail_msmtp', fake_send_mail)

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        client.post('/contact', data={'message': 'Hello'}, follow_redirects=True)

        assert len(calls) == 2
        rec1 = calls[0][2]
        rec2 = calls[1][2]
        rec1_set = set(rec1 if isinstance(rec1, (list, set)) else [rec1])
        rec2_set = set(rec2 if isinstance(rec2, (list, set)) else [rec2])
        assert rec1_set == {admin.email}
        assert rec2_set == {user.email}
        db.drop_all()
