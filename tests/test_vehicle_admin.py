import pytest
from app import app
from models import db, User, Vehicle


@pytest.fixture
def client():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        admin = User(
            name='Admin User',
            first_name='Admin',
            last_name='User',
            email='admin@example.com',
            role=User.ROLE_ADMIN,
            password_hash='x',
        )
        db.session.add(admin)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = admin.id
        yield client
        db.drop_all()


def test_vehicle_list_and_edit(client):
    with app.app_context():
        v = Vehicle(code='C1', label='Car1', category='Old')
        db.session.add(v)
        db.session.commit()
        vid = v.id
    rv = client.get('/admin/vehicles')
    assert rv.status_code == 200
    assert b'Old' in rv.data
    rv = client.post(f'/admin/vehicles/{vid}/edit', data={'code': 'C1', 'label': 'Car1', 'category': 'New'}, follow_redirects=True)
    assert rv.status_code == 200
    with app.app_context():
        v = Vehicle.query.get(vid)
        assert v.category == 'New'
