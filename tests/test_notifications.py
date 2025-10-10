import json
from datetime import datetime

from app import app
from models import (
    db,
    User,
    Vehicle,
    Reservation,
    ReservationSegment,
    NotificationSettings,
)


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
    app.config['SUPERADMIN_EMAILS'] = ['legacy@example.com']
    app.config['ADMIN_EMAILS'] = ['legacy-admin@example.com']
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

        def fake_send_mail(subject, body, recipients, sender="gestionvehiculestomer@gmail.com", profile="gmail"):
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
        assert 'legacy@example.com' not in admin_recipients
        assert 'legacy-admin@example.com' not in admin_recipients
        assert user_recipients == {user.email}
        db.drop_all()


def test_new_request_notifies_users_when_ids_are_strings(monkeypatch):
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

        settings = NotificationSettings(
            notify_user_ids=[str(sa.id), f" {ad.id} "]
        )
        db.session.add(settings)
        db.session.commit()

        captured = []

        def fake_send_mail(subject, body, recipients, **kwargs):
            captured.append(list(recipients))

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

        assert captured, "Expected a notification email"
        admin_recipients = captured[0]
        assert sorted(admin_recipients) == sorted([sa.email, ad.email])
        db.drop_all()


def test_new_request_handles_json_string_ids(monkeypatch):
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

        settings = NotificationSettings(
            notify_user_ids=f"[{sa.id}, {ad.id}]"
        )
        db.session.add(settings)
        db.session.commit()

        captured = []

        def fake_send_mail(subject, body, recipients, **kwargs):
            captured.append(list(recipients))

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

        assert captured, "Expected a notification email"
        admin_recipients = captured[0]
        assert sorted(admin_recipients) == sorted([sa.email, ad.email])
        db.drop_all()


def test_manage_request_approval_notifies_carpoolers(monkeypatch):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        admin = User(
            name='Admin User',
            first_name='Admin',
            last_name='User',
            email='admin@example.com',
            role=User.ROLE_ADMIN,
            password_hash='x',
            status='active',
        )
        requester = User(
            name='Requester User',
            first_name='Requester',
            last_name='User',
            email='requester@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        carpool_active = User(
            name='Active Carpooler',
            first_name='Active',
            last_name='Carpooler',
            email='carpool-active@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        carpool_inactive = User(
            name='Inactive Carpooler',
            first_name='Inactive',
            last_name='Carpooler',
            email='carpool-inactive@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='inactive',
        )
        vehicle = Vehicle(code='V1', label='Vehicule 1')
        db.session.add_all([admin, requester, carpool_active, carpool_inactive, vehicle])
        db.session.commit()

        calls = []

        def fake_send_mail(subject, body, recipients, sender="gestionvehiculestomer@gmail.com", profile="gmail"):
            if isinstance(recipients, str):
                rec_list = [recipients]
            else:
                rec_list = list(recipients)
            calls.append((subject, rec_list))
            return True

        monkeypatch.setattr('app.send_mail_msmtp', fake_send_mail)

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = requester.id
        data = {
            'first_name': requester.first_name,
            'last_name': requester.last_name,
            'start_date': '2024-01-01',
            'start_slot': 'day',
            'end_date': '2024-01-01',
            'end_slot': 'day',
            'purpose': '',
            'carpool': 'y',
            'carpool_with': 'Active, Inactive',
            'carpool_with_ids': json.dumps([
                {'id': carpool_active.id, 'label': 'Active Carpooler'},
                {'id': carpool_inactive.id, 'label': 'Inactive Carpooler'},
            ]),
            'notes': '',
        }
        client.post('/request/new', data=data, follow_redirects=True)
        reservation = Reservation.query.filter_by(user_id=requester.id).first()
        assert reservation is not None
        calls.clear()

        with client.session_transaction() as sess:
            sess['uid'] = admin.id
        approve_data = {'action': 'approve', 'vehicle_id': str(vehicle.id)}
        client.post(f'/admin/manage/{reservation.id}', data=approve_data, follow_redirects=True)

        assert len(calls) == 1
        subject, recipients = calls[0]
        assert subject == 'Réservation validée'
        assert set(recipients) == {requester.email, carpool_active.email}
        assert carpool_inactive.email not in recipients


def test_manage_request_approval_includes_manual_carpool_email(monkeypatch):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        admin = User(
            name='Admin User',
            first_name='Admin',
            last_name='User',
            email='admin@example.com',
            role=User.ROLE_ADMIN,
            password_hash='x',
            status='active',
        )
        requester = User(
            name='Requester User',
            first_name='Requester',
            last_name='User',
            email='requester@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        vehicle = Vehicle(code='V1', label='Vehicule 1')
        db.session.add_all([admin, requester, vehicle])
        db.session.commit()

        captured = []

        def fake_send_mail(subject, body, recipients, sender="gestionvehiculestomer@gmail.com", profile="gmail"):
            if isinstance(recipients, str):
                rec_list = [recipients]
            else:
                rec_list = list(recipients)
            captured.append((subject, rec_list))
            return True

        monkeypatch.setattr('app.send_mail_msmtp', fake_send_mail)

        manual_email = 'friend.carpool@example.net'

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = requester.id
        data = {
            'first_name': requester.first_name,
            'last_name': requester.last_name,
            'start_date': '2024-01-01',
            'start_slot': 'day',
            'end_date': '2024-01-01',
            'end_slot': 'day',
            'purpose': '',
            'carpool': 'y',
            'carpool_with': manual_email,
            'carpool_with_ids': '',
            'notes': '',
        }
        client.post('/request/new', data=data, follow_redirects=True)
        reservation = Reservation.query.filter_by(user_id=requester.id).first()
        assert reservation is not None

        captured.clear()

        with client.session_transaction() as sess:
            sess['uid'] = admin.id
        approve_data = {'action': 'approve', 'vehicle_id': str(vehicle.id)}
        client.post(f'/admin/manage/{reservation.id}', data=approve_data, follow_redirects=True)

        assert len(captured) == 1
        subject, recipients = captured[0]
        assert subject == 'Réservation validée'
        assert set(recipients) == {requester.email, manual_email}
        db.drop_all()


def test_manage_segment_change_vehicle_notifies_carpoolers(monkeypatch):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        admin = User(
            name='Admin User',
            first_name='Admin',
            last_name='User',
            email='admin@example.com',
            role=User.ROLE_ADMIN,
            password_hash='x',
            status='active',
        )
        requester = User(
            name='Requester User',
            first_name='Requester',
            last_name='User',
            email='requester@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        carpool_active = User(
            name='Active Carpooler',
            first_name='Active',
            last_name='Carpooler',
            email='carpool-active@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='active',
        )
        carpool_inactive = User(
            name='Inactive Carpooler',
            first_name='Inactive',
            last_name='Carpooler',
            email='carpool-inactive@example.com',
            role=User.ROLE_USER,
            password_hash='x',
            status='inactive',
        )
        vehicle_old = Vehicle(code='VOLD', label='Vehicule Ancien')
        vehicle_new = Vehicle(code='VNEW', label='Vehicule Nouveau')
        db.session.add_all([
            admin,
            requester,
            carpool_active,
            carpool_inactive,
            vehicle_old,
            vehicle_new,
        ])
        db.session.commit()

        reservation = Reservation(
            user_id=requester.id,
            start_at=datetime(2024, 1, 1, 8, 0),
            end_at=datetime(2024, 1, 1, 12, 0),
            status='approved',
            carpool=True,
            carpool_with_ids=[carpool_active.id, carpool_inactive.id],
            carpool_with_details=[
                {
                    'id': carpool_active.id,
                    'email': carpool_active.email,
                    'name': carpool_active.name,
                    'status': carpool_active.status,
                },
                {
                    'id': carpool_inactive.id,
                    'email': carpool_inactive.email,
                    'name': carpool_inactive.name,
                    'status': carpool_inactive.status,
                },
            ],
        )
        db.session.add(reservation)
        db.session.commit()

        segment = ReservationSegment(
            reservation_id=reservation.id,
            vehicle_id=vehicle_old.id,
            start_at=datetime(2024, 1, 1, 8, 0),
            end_at=datetime(2024, 1, 1, 12, 0),
        )
        db.session.add(segment)
        db.session.commit()

        calls = []

        def fake_send_mail(subject, body, recipients, sender="gestionvehiculestomer@gmail.com", profile="gmail"):
            if isinstance(recipients, str):
                rec_list = [recipients]
            else:
                rec_list = list(recipients)
            calls.append((subject, rec_list))
            return True

        monkeypatch.setattr('app.send_mail_msmtp', fake_send_mail)

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = admin.id
        update_data = {'action': 'update', 'vehicle_id': str(vehicle_new.id)}
        client.post(f'/admin/manage/segment/{segment.id}', data=update_data, follow_redirects=True)

        assert len(calls) == 1
        subject, recipients = calls[0]
        assert subject == 'Modification de votre réservation'
        assert set(recipients) == {requester.email, carpool_active.email}
        assert carpool_inactive.email not in recipients
        db.drop_all()
