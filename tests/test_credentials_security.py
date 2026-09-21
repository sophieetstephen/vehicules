"""Le mot de passe ne doit jamais partir dans le cookie, et une régénération
doit fermer les sessions déjà ouvertes.
"""

import importlib
import json

import pytest

from app import app
from models import db, User, CredentialHandoff

app_module = importlib.import_module("app")
MDP = "Kx7m-Rp2v-Q9wT"


@pytest.fixture
def ctx(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.drop_all()


def _user(first, last, email, role=User.ROLE_USER, password=MDP):
    u = User(name=f"{last} {first}", first_name=first, last_name=last, email=email,
             role=role, status="active")
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    u.assign_username()
    db.session.commit()
    return u


def _connecte(user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = user.id
        s["pwd_stamp"] = user.session_stamp(app.config["SECRET_KEY"])
    return c


def _contenu_session(client):
    with client.session_transaction() as s:
        return dict(s)


# --- le mot de passe ne sort pas du serveur ---------------------------------

def test_new_account_password_stays_server_side(ctx):
    boss = _user("Super", "Admin", "boss@ex.fr", role=User.ROLE_SUPERADMIN)
    client = _connecte(boss)
    resp = client.post("/admin/users/new", data={
        "first_name": "Jean", "last_name": "Dupont",
        "email": "jean@sdis62.fr", "role": "user"})
    assert resp.status_code == 302

    handoff = CredentialHandoff.query.one()
    mot_de_passe = handoff.password

    session_dict = _contenu_session(client)
    assert "pending_credentials" not in session_dict
    assert "credentials_token" in session_dict
    assert mot_de_passe not in json.dumps(session_dict, default=str)

    # Le cookie réellement envoyé au navigateur ne contient pas le mot de passe.
    cookie_envoye = resp.headers.get("Set-Cookie", "")
    assert cookie_envoye, "la réponse doit bien poser un cookie de session"
    assert mot_de_passe not in cookie_envoye

    # Il reste affiché une seule fois, puis la ligne serveur disparaît.
    html = client.get("/admin/users/credentials").data.decode()
    assert mot_de_passe in html and "dupontj" in html
    assert CredentialHandoff.query.count() == 0
    assert client.get("/admin/users/credentials").status_code == 302


def test_regenerated_password_stays_server_side(ctx):
    boss = _user("Super", "Admin", "boss@ex.fr", role=User.ROLE_SUPERADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    client = _connecte(boss)
    client.post(f"/admin/reset_password/{jean.id}")
    mot_de_passe = CredentialHandoff.query.one().password
    assert mot_de_passe not in json.dumps(_contenu_session(client), default=str)
    assert mot_de_passe in client.get("/admin/users/credentials").data.decode()


def test_credentials_page_is_reserved_to_its_admin(ctx):
    boss = _user("Super", "Admin", "boss@ex.fr", role=User.ROLE_SUPERADMIN)
    autre = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    client = _connecte(boss)
    client.post("/admin/users/new", data={
        "first_name": "Jean", "last_name": "Dupont",
        "email": "jean@sdis62.fr", "role": "user"})
    # Le jeton est dans la session du créateur : un autre admin ne voit rien.
    assert _connecte(autre).get("/admin/users/credentials").status_code == 302
    assert CredentialHandoff.query.count() == 1


def test_expired_handoff_is_not_shown(ctx):
    from datetime import datetime, timedelta
    boss = _user("Super", "Admin", "boss@ex.fr", role=User.ROLE_SUPERADMIN)
    client = _connecte(boss)
    client.post("/admin/users/new", data={
        "first_name": "Jean", "last_name": "Dupont",
        "email": "jean@sdis62.fr", "role": "user"})
    handoff = CredentialHandoff.query.one()
    handoff.created_at = datetime.utcnow() - timedelta(
        minutes=CredentialHandoff.MAX_AGE_MINUTES + 1)
    db.session.commit()
    assert client.get("/admin/users/credentials").status_code == 302
    assert CredentialHandoff.query.count() == 0, "la ligne périmée est purgée"


# --- une régénération ferme les sessions ouvertes ----------------------------

def test_regenerating_password_closes_open_sessions(ctx):
    boss = _user("Super", "Admin", "boss@ex.fr", role=User.ROLE_SUPERADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")

    jean_client = app.test_client()
    assert jean_client.post("/login", data={"username": "dupontj", "password": MDP}).status_code == 302
    assert jean_client.get("/request/new").status_code == 200

    _connecte(boss).post(f"/admin/reset_password/{jean.id}")

    resp = jean_client.get("/request/new")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login")
    assert jean_client.get("/home").headers["Location"].endswith("/login")
    with jean_client.session_transaction() as s:
        assert "uid" not in s


def test_own_session_survives_regenerating_someone_else(ctx):
    boss = _user("Super", "Admin", "boss@ex.fr", role=User.ROLE_SUPERADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    client = _connecte(boss)
    client.post(f"/admin/reset_password/{jean.id}")
    assert client.get("/admin/users").status_code == 200


def test_session_without_stamp_is_refused(ctx):
    """Les sessions ouvertes avant ce correctif doivent être renouvelées."""
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = jean.id  # ancienne forme, sans empreinte
    resp = client.get("/request/new")
    assert resp.status_code == 302 and resp.headers["Location"].startswith("/login")


def test_deleted_account_session_is_refused(ctx):
    boss = _user("Super", "Admin", "boss@ex.fr", role=User.ROLE_SUPERADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    jean_client = _connecte(jean)
    _connecte(boss).post(f"/admin/delete/{jean.id}")
    resp = jean_client.get("/request/new")
    assert resp.status_code == 302 and resp.headers["Location"].startswith("/login")
