import pytest

from app import app
from models import db, User


def create_user(first_name, last_name, email, role=User.ROLE_USER, status='active'):
    return User(
        name=f"{last_name} {first_name}".strip(),
        first_name=first_name,
        last_name=last_name,
        email=email,
        role=role,
        password_hash='x',
        status=status,
    )


def setup_app():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False


def test_search_users_returns_matches_and_excludes_current_user():
    setup_app()
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        current = create_user('Charlie', 'Current', 'current@example.com')
        match_one = create_user('Alice', 'Martin', 'alice@example.com')
        match_two = create_user('Alfred', 'Dupont', 'alfred@example.com')
        other = create_user('Zoé', 'Brun', 'zoe@example.com')
        inactive = create_user('Alan', 'Inactive', 'inactive@example.com', status='pending')
        db.session.add_all([current, match_one, match_two, other, inactive])
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = current.id

        response = client.get('/api/users/search?q=al')
        assert response.status_code == 200
        payload = response.get_json()
        labels = {entry['label'] for entry in payload}
        ids = {entry['id'] for entry in payload}

        assert match_one.id in ids
        assert match_two.id in ids
        assert 'Alice Martin' in labels
        assert 'Alfred Dupont' in labels
        assert current.id not in ids
        assert inactive.id not in ids
        assert other.id not in ids

        # empty search should return no suggestions
        empty_response = client.get('/api/users/search?q=')
        assert empty_response.status_code == 200
        assert empty_response.get_json() == []

        db.drop_all()


def test_search_users_allows_admin_to_include_self():
    setup_app()
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        admin = create_user('Ada', 'Admin', 'admin@example.com', role=User.ROLE_ADMIN)
        colleague = create_user('Alan', 'Cooper', 'alan@example.com')
        db.session.add_all([admin, colleague])
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = admin.id

        response = client.get('/api/users/search?q=ad&include_self=1')
        assert response.status_code == 200
        payload = response.get_json()
        ids = {entry['id'] for entry in payload}
        assert admin.id in ids

        without_flag = client.get('/api/users/search?q=ad')
        assert without_flag.status_code == 200
        ids_without_flag = {entry['id'] for entry in without_flag.get_json()}
        assert admin.id not in ids_without_flag

        db.drop_all()


def test_search_users_include_self_flag_ignored_for_regular_user():
    setup_app()
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        regular = create_user('Rex', 'Regular', 'regular@example.com')
        other = create_user('Rita', 'Rivers', 'rita@example.com')
        db.session.add_all([regular, other])
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['uid'] = regular.id

        response = client.get('/api/users/search?q=ri&include_self=1')
        assert response.status_code == 200
        payload = response.get_json()
        ids = {entry['id'] for entry in payload}
        assert regular.id not in ids
        assert other.id in ids

        db.drop_all()

