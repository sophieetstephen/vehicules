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
        assert 'class="login-card"' in html
        assert 'class="form-label"' in html
        # Connexion par identifiant : plus de champ e-mail ni d'inscription publique.
        assert 'Identifiant' in html
        assert 'name="username"' in html
        assert 'type="email"' not in html
        assert 'Créer un compte' not in html
        assert '/register' not in html
        db.drop_all()


def test_register_and_reset_routes_are_gone():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        client = app.test_client()
        # Non authentifié : redirigé vers /login (pas de page d'inscription).
        assert client.get('/register').status_code == 302
        assert client.get('/reset/abc').status_code == 302
        db.drop_all()
