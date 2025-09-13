import pytest
from app import app
from models import db, User, NotificationSettings


def setup_users():
    sa = User(
        name='Super Admin',
        first_name='Super',
        last_name='Admin',
        email='super@example.com',
        role=User.ROLE_SUPERADMIN,
        password_hash='x',
        status='active',
    )
    ad = User(
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
    return sa, ad, user


def test_admin_leaves_renders_checkboxes():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        sa, ad, user = setup_users()
        db.session.add_all([sa, ad, user])
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = sa.id
        resp = client.get('/admin/leaves')
        html = resp.data.decode('utf-8')
        assert f'{sa.first_name} {sa.last_name}' in html
        assert f'{ad.first_name} {ad.last_name}' in html
        assert f'{user.first_name} {user.last_name}' not in html
        db.drop_all()


def test_new_request_notifies_selected_users(monkeypatch):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        sa, ad, user = setup_users()
        other = User(
            name='Other Admin',
            first_name='Other',
            last_name='Admin',
            email='other@example.com',
            role=User.ROLE_ADMIN,
            password_hash='x',
            status='active',
        )
        db.session.add_all([sa, ad, other, user])
        db.session.commit()
        settings = NotificationSettings(notify_user_ids=[sa.id, ad.id])
        db.session.add(settings)
        db.session.commit()

        calls = []

        def fake_send_mail(subject, body, recipients):
            if isinstance(recipients, str):
                calls.append({recipients})
            else:
                calls.append(set(recipients))

        monkeypatch.setattr('app.send_mail_msmtp', fake_send_mail)

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = user.id
        data = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'start_date': '2024-01-01',
            'start_slot': 'day',
            'end_date': '2024-01-01',
            'end_slot': 'day',
            'purpose': '',
            'carpool': '',
            'carpool_with': '',
            'notes': '',
        }
        client.post('/request/new', data=data, follow_redirects=True)
        assert len(calls) == 2
        admin_recipients, user_recipients = calls
        assert admin_recipients == {sa.email, ad.email}
        assert other.email not in admin_recipients
        assert user_recipients == {user.email}
        db.drop_all()
