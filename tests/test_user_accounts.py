"""Comptes créés par un administrateur, identifiant + mot de passe générés."""

import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from models import db, User
from utils import build_username_base, generate_password, slugify_name

app_module = importlib.import_module("app")


def _setup():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    db.session.remove()
    db.drop_all()
    db.create_all()


def _make_user(first, last, email, role=User.ROLE_USER, password="Secret-1234", status="active"):
    u = User(
        name=f"{last} {first}",
        first_name=first,
        last_name=last,
        email=email,
        role=role,
        status=status,
    )
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    u.assign_username()
    db.session.commit()
    return u


def _capture_mail(monkeypatch):
    calls = []

    def fake_send_mail(subject, body, to_addrs, *args, **kwargs):
        calls.append({"subject": subject, "body": body, "to": to_addrs})
        return True, "sent"

    monkeypatch.setattr(app_module, "send_mail_msmtp", fake_send_mail)
    return calls


# --- helpers purs -----------------------------------------------------------

def test_slugify_removes_accents_spaces_and_case():
    assert slugify_name("Le Roux-Élé") == "lerouxele"
    assert slugify_name("  Ça ") == "ca"
    assert slugify_name(None) == ""


def test_username_base_is_lastname_plus_initial():
    assert build_username_base(first_name="Jean", last_name="Dupont") == "dupontj"
    assert build_username_base(first_name="Élodie", last_name="De La Tour") == "delatoure"
    # Repli sur la colonne "name" (format "Nom Prénom") pour les anciens comptes.
    assert build_username_base(name="Super Admin", email="x@y.z") == "supera"
    # Dernier repli : partie locale de l'e-mail.
    assert build_username_base(email="chef.centre@sdis62.fr") == "chefcentre"


def test_generate_password_shape_and_randomness():
    pwd = generate_password()
    assert len(pwd) == 14 and pwd.count("-") == 2
    for ch in pwd.replace("-", ""):
        assert ch not in "0O1lI"
    assert generate_password() != generate_password()


# --- identifiants uniques ---------------------------------------------------

def test_assign_username_adds_suffix_on_collision():
    with app.app_context():
        _setup()
        a = _make_user("Jean", "Dupont", "a@example.com")
        b = _make_user("Julie", "Dupont", "b@example.com")
        c = _make_user("Jacques", "Dupont", "c@example.com")
        assert (a.username, b.username, c.username) == ("dupontj", "dupontj2", "dupontj3")
        db.drop_all()


# --- connexion --------------------------------------------------------------

def test_login_uses_username_not_email():
    with app.app_context():
        _setup()
        user = _make_user("Jean", "Dupont", "jean@example.com", password="Kx7m-Rp2v-Q9wT")
        client = app.test_client()

        resp = client.post("/login", data={"username": "jean@example.com", "password": "Kx7m-Rp2v-Q9wT"})
        assert resp.status_code == 200 and "Identifiants invalides" in resp.data.decode()

        resp = client.post("/login", data={"username": " DupontJ ", "password": "Kx7m-Rp2v-Q9wT"})
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get("uid") == user.id
        db.drop_all()


def test_login_next_parameter_rejects_external_urls():
    with app.app_context():
        _setup()
        _make_user("Jean", "Dupont", "jean@example.com", password="Kx7m-Rp2v-Q9wT")
        client = app.test_client()
        resp = client.post(
            "/login?next=https://evil.example/phish",
            data={"username": "dupontj", "password": "Kx7m-Rp2v-Q9wT"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/home") or resp.headers["Location"] == "/"
        client.get("/logout")
        resp = client.post(
            "/login?next=/calendar/month",
            data={"username": "dupontj", "password": "Kx7m-Rp2v-Q9wT"},
        )
        assert resp.headers["Location"] == "/calendar/month"
        db.drop_all()


# --- création par un administrateur ----------------------------------------

def test_admin_creates_user_with_generated_credentials(monkeypatch):
    with app.app_context():
        _setup()
        calls = _capture_mail(monkeypatch)
        admin = _make_user("Alex", "Chef", "chef@example.com", role=User.ROLE_ADMIN)
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["uid"] = admin.id

        resp = client.post(
            "/admin/users/new",
            data={
                "first_name": "Jean",
                "last_name": "Dupont",
                "email": "Jean.Dupont@sdis62.fr",
                "role": "superadmin",  # ignoré pour un simple admin
            },
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/users/credentials")

        created = User.query.filter_by(email="jean.dupont@sdis62.fr").one()
        assert created.username == "dupontj"
        assert created.status == "active"
        assert created.role == User.ROLE_USER

        # Le mot de passe est envoyé par mail à l'utilisateur uniquement.
        assert len(calls) == 1
        assert calls[0]["to"] == "jean.dupont@sdis62.fr"
        assert "Identifiant : dupontj" in calls[0]["body"]
        password = calls[0]["body"].split("Mot de passe : ")[1].splitlines()[0]
        assert created.check_password(password)

        # Affichage unique des identifiants.
        page = client.get("/admin/users/credentials")
        html = page.data.decode()
        assert "dupontj" in html and password in html
        assert client.get("/admin/users/credentials").status_code == 302

        # L'utilisateur peut se connecter avec ces identifiants.
        other = app.test_client()
        assert other.post("/login", data={"username": "dupontj", "password": password}).status_code == 302
        db.drop_all()


def test_admin_cannot_create_duplicate_email(monkeypatch):
    with app.app_context():
        _setup()
        _capture_mail(monkeypatch)
        admin = _make_user("Alex", "Chef", "chef@example.com", role=User.ROLE_ADMIN)
        _make_user("Jean", "Dupont", "jean@example.com")
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["uid"] = admin.id
        resp = client.post(
            "/admin/users/new",
            data={"first_name": "Jean", "last_name": "Dupont", "email": "jean@example.com", "role": "user"},
        )
        assert resp.status_code == 200
        assert "déjà utilisée" in resp.data.decode()
        assert User.query.count() == 2
        db.drop_all()


def test_simple_user_cannot_create_accounts():
    with app.app_context():
        _setup()
        user = _make_user("Jean", "Dupont", "jean@example.com")
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["uid"] = user.id
        assert client.get("/admin/users/new").status_code == 403
        assert client.post(
            "/admin/users/new",
            data={"first_name": "X", "last_name": "Y", "email": "x@y.fr", "role": "user"},
        ).status_code == 403
        assert User.query.count() == 1
        db.drop_all()


# --- régénération du mot de passe -----------------------------------------

def test_superadmin_regenerates_password(monkeypatch):
    with app.app_context():
        _setup()
        calls = _capture_mail(monkeypatch)
        boss = _make_user("Super", "Admin", "boss@example.com", role=User.ROLE_SUPERADMIN)
        target = _make_user("Jean", "Dupont", "jean@example.com", password="Old-Pass-1234")
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["uid"] = boss.id

        resp = client.post(f"/admin/reset_password/{target.id}")
        assert resp.status_code == 302
        refreshed = db.session.get(User, target.id)
        assert not refreshed.check_password("Old-Pass-1234")
        assert calls and calls[-1]["to"] == "jean@example.com"
        new_password = calls[-1]["body"].split("Mot de passe : ")[1].splitlines()[0]
        assert refreshed.check_password(new_password)
        html = client.get("/admin/users/credentials").data.decode()
        assert new_password in html and "dupontj" in html
        db.drop_all()


def test_admin_cannot_regenerate_password():
    with app.app_context():
        _setup()
        admin = _make_user("Alex", "Chef", "chef@example.com", role=User.ROLE_ADMIN)
        target = _make_user("Jean", "Dupont", "jean@example.com", password="Old-Pass-1234")
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["uid"] = admin.id
        assert client.post(f"/admin/reset_password/{target.id}").status_code == 403
        assert db.session.get(User, target.id).check_password("Old-Pass-1234")
        db.drop_all()


def test_superadmin_keeps_access_after_legacy_migration_shape():
    """Un compte historique sans prénom/nom reçoit un identifiant utilisable."""
    with app.app_context():
        _setup()
        legacy = User(
            name="Super Admin",
            email="gestionvehiculestomer@gmail.com",
            role=User.ROLE_SUPERADMIN,
            status="active",
        )
        legacy.set_password("Whatever-123")
        db.session.add(legacy)
        db.session.commit()
        legacy.assign_username()
        db.session.commit()
        assert legacy.username == "supera"
        client = app.test_client()
        resp = client.post("/login", data={"username": "supera", "password": "Whatever-123"})
        assert resp.status_code == 302
        db.drop_all()
