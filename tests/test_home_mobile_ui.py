"""Accueil sur téléphone : raccourcis accessibles sans défiler.

L'état des véhicules et les réservations à venir occupaient plusieurs écrans
avant les grandes tuiles. Les véhicules sont compactés en lignes, les tuiles
deviennent des bandeaux, et deux boutons d'accès direct sont ajoutés en haut.
"""

import pathlib

import pytest

from app import app
from models import db, User, Vehicle

CSS = pathlib.Path("static/custom.css").read_text(encoding="utf-8")


@pytest.fixture
def ctx():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        for code in ("VL1", "VL2", "VID2", "VIDXL", "VRID"):
            db.session.add(Vehicle(code=code, label=f"Véhicule {code}"))
        db.session.commit()
        yield
        db.drop_all()


def _accueil(role):
    u = User(name="Dupont Jean", first_name="Jean", last_name="Dupont",
             username=f"dupontj{role[:2]}", email=f"{role}@ex.fr", role=role,
             status="active", password_hash="x")
    db.session.add(u)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = u.id
        s["pwd_stamp"] = u.session_stamp(app.config["SECRET_KEY"])
    return client.get("/home").data.decode()


@pytest.mark.parametrize("role", [User.ROLE_USER, User.ROLE_ADMIN, User.ROLE_SUPERADMIN])
def test_quick_actions_on_every_home(ctx, role):
    html = _accueil(role)
    bloc = html.split('class="quick-actions')[1].split("</div>")[0]
    assert "Réserver" in bloc and "Planning" in bloc
    assert "/request/new" in bloc and "/calendar/month" in bloc


@pytest.mark.parametrize("role", [User.ROLE_USER, User.ROLE_ADMIN, User.ROLE_SUPERADMIN])
def test_quick_actions_come_before_today_and_tiles(ctx, role):
    """Sur téléphone, ils doivent être atteignables dès le haut de page."""
    html = _accueil(role)
    assert html.index("quick-actions") < html.index("Aujourd'hui")
    assert html.index("quick-actions") < html.index("dashboard-card")


def test_quick_actions_hidden_on_desktop(ctx):
    """Sur ordinateur, les grandes tuiles sont déjà visibles : pas de doublon."""
    html = _accueil(User.ROLE_USER)
    entete = html.split('class="quick-actions')[1][:40]
    assert "d-md-none" in entete


def test_vehicle_rows_are_compact_on_mobile(ctx):
    html = _accueil(User.ROLE_USER)
    regles = html.split("@media (max-width: 768px)")[1]
    assert ".vehicle-status-label { display: none; }" in regles
    assert ".vehicle-status { padding: 0.55rem" in regles


def test_no_stray_separator_before_wrapped_lines(ctx):
    """Le point médian en début de ligne a été retiré."""
    html = _accueil(User.ROLE_USER)
    assert 'content: " · "' not in html


def test_dashboard_tiles_become_bands_on_mobile():
    mobile = CSS.split("@media (max-width: 768px)")[1]
    bloc = mobile.split(".dashboard-card {")[1].split("}")[0]
    assert "flex-direction: row" in bloc
    assert "min-height: 0" in bloc


def test_install_banner_limited_to_phones(ctx):
    """Chrome déclenche beforeinstallprompt aussi sur ordinateur."""
    html = _accueil(User.ROLE_USER)
    handler = html.split("beforeinstallprompt")[1].split("});")[0]
    assert "isMobile" in handler, "le bandeau ne doit pas s'afficher sur un poste fixe"


def test_install_banner_button_is_readable(ctx):
    """Le lien d'aide était en contour clair sur fond cyan, illisible."""
    html = _accueil(User.ROLE_USER)
    # Le bandeau va de son identifiant jusqu'au bouton « Plus tard ».
    bandeau = html.split('id="pwa-banner"')[1].split("Plus tard")[0]
    assert "/installer" in bandeau, "le lien d'aide doit être dans le bandeau"
    assert "btn-outline-primary" not in bandeau, "contraste insuffisant sur fond cyan"
