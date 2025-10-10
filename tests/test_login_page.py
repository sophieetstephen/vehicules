from app import app
from models import db


def test_login_page_bootstrap_classes():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        client = app.test_client()
        resp = client.get('/login')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'class="card' in html
        assert 'class="form-label"' in html
        assert 'Créer un compte' in html
        assert 'Première connexion' not in html
        db.drop_all()
