"""Hygiène des secrets : mots de passe en clair, cache, git, cookies.

Audit du 24/09/2026, reproduit : une remise d'identifiants vieille de deux jours
restait en base, mot de passe en clair compris, et partait dans les
sauvegardes ; les copies du .env n'étaient pas exclues de git ; le cookie de
session n'était ni ``Secure`` ni ``SameSite``.
"""

import importlib
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

from app import app, purge_expired_credentials
from models import db, User, CredentialHandoff

app_module = importlib.import_module("app")
RACINE = pathlib.Path(__file__).resolve().parents[1]


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


def _user(role=User.ROLE_SUPERADMIN, prenom="Chef"):
    u = User(name=f"X {prenom}", first_name=prenom, last_name="X",
             email=f"{prenom.lower()}@ex.fr", role=role, status="active", password_hash="x")
    db.session.add(u)
    db.session.flush()
    u.assign_username()
    db.session.commit()
    return u


def _client(u):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = u.id
        s["pwd_stamp"] = u.session_stamp(app.config["SECRET_KEY"])
    return c


def _remise(user, age, jeton):
    db.session.add(CredentialHandoff(
        token=jeton, user_id=user.id, password="EnClair-1234", regenerated=False,
        mail_sent=True, created_at=datetime.utcnow() - age))
    db.session.commit()


# --- mots de passe en clair ----------------------------------------------------

def test_abandoned_password_is_erased_by_an_ordinary_request(ctx):
    """Reproduit par l'audit : elle subsistait deux jours plus tard."""
    chef = _user()
    _remise(chef, timedelta(days=2), "vieux")
    _client(chef).get("/")
    assert CredentialHandoff.query.filter_by(token="vieux").first() is None


def test_fresh_password_waits_for_its_display(ctx):
    """Le délai couvre la redirection vers l'écran d'affichage."""
    chef = _user()
    _remise(chef, timedelta(seconds=5), "frais")
    _client(chef).get("/")
    assert CredentialHandoff.query.filter_by(token="frais").first() is not None


def test_purge_does_not_write_when_nothing_expired(ctx, monkeypatch):
    """Une écriture à chaque page prendrait le verrou de SQLite pour rien."""
    chef = _user()
    _remise(chef, timedelta(seconds=5), "frais")
    ecritures = []
    monkeypatch.setattr(db.session, "commit", lambda: ecritures.append(1))
    assert purge_expired_credentials() == 0
    assert ecritures == []


def test_lifetime_is_short():
    """Une redirection prend une seconde : dix minutes étaient superflues."""
    assert CredentialHandoff.MAX_AGE_MINUTES <= 5


def test_credentials_page_is_never_cached(ctx):
    """Le bouton « Précédent » ne doit pas pouvoir réafficher un mot de passe."""
    chef = _user()
    jean = _user(User.ROLE_USER, "Jean")
    c = _client(chef)
    c.post(f"/admin/reset_password/{jean.id}")
    reponse = c.get("/admin/users/credentials")
    assert reponse.status_code == 200
    assert "no-store" in reponse.headers.get("Cache-Control", "")


# --- git -----------------------------------------------------------------------

@pytest.mark.parametrize("chemin", [
    "backups/vehicules_20260101_000000.db.gz",
    "backups/env_20260101_000000.txt",
    "backups/archives/2025/planning_2025-01.pdf",
    "env_20260101_000000.txt",
    "rclone.conf",
    ".env",
])
def test_backups_and_secrets_are_ignored_by_git(chemin):
    """« backup/ » au singulier ne couvrait pas le dossier « backups/ », où
    dort chaque nuit une copie du .env."""
    try:
        resultat = subprocess.run(["git", "check-ignore", "-q", chemin], cwd=RACINE)
    except FileNotFoundError:
        pytest.skip("git absent")
    if resultat.returncode == 128:
        pytest.skip("hors dépôt git")
    assert resultat.returncode == 0, f"{chemin} serait versionné"


# --- cookie de session -----------------------------------------------------------

def _config_sans(variable):
    """Lire la configuration telle qu'en production, sans surcharge de test."""
    env = {k: v for k, v in os.environ.items() if k != variable}
    code = ("from config import Config; "
            "print(Config.SESSION_COOKIE_SECURE, Config.SESSION_COOKIE_HTTPONLY, "
            "Config.SESSION_COOKIE_SAMESITE)")
    sortie = subprocess.run([sys.executable, "-c", code], cwd=RACINE, env=env,
                            capture_output=True, text=True, check=True)
    return sortie.stdout.split()


def test_session_cookie_is_secure_by_default():
    """Le site n'est servi qu'en HTTPS derrière Caddy."""
    secure, httponly, samesite = _config_sans("SESSION_COOKIE_SECURE")
    assert secure == "True"
    assert httponly == "True"
    assert samesite == "Lax"
