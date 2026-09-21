"""La feuille de style corrigée doit atteindre les navigateurs déjà venus.

Le service worker mettait ``custom.css`` en cache et le resservait
indéfiniment : une correction de style restait invisible tant que le nom du
cache n'était pas changé à la main. L'adresse porte désormais l'empreinte du
contenu, et le cache se rafraîchit en arrière-plan.
"""

import pathlib
import re

import pytest

import app as app_module
from app import app, static_version
from models import db, User

SW = pathlib.Path("static/service-worker.js").read_text(encoding="utf-8")


@pytest.fixture
def ctx():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.drop_all()


def _connecte():
    u = User(name="Dupont Jean", first_name="Jean", last_name="Dupont", username="dupontj",
             email="j@ex.fr", role=User.ROLE_USER, status="active", password_hash="x")
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = u.id
        s["pwd_stamp"] = u.session_stamp(app.config["SECRET_KEY"])
    return c


def test_stylesheet_url_carries_a_version(ctx):
    for page in (app.test_client().get("/login"), _connecte().get("/home")):
        html = page.data.decode()
        trouve = re.search(r"custom\.css\?v=([0-9a-f]{8})", html)
        assert trouve, "l'adresse doit porter une empreinte"
        assert trouve.group(1) == static_version("custom.css")


def test_version_follows_content(ctx):
    fichier = pathlib.Path("static/custom.css")
    origine = fichier.read_text(encoding="utf-8")
    avant = static_version("custom.css")
    try:
        fichier.write_text(origine + "\n/* modification */\n", encoding="utf-8")
        app_module._static_versions.clear()
        assert static_version("custom.css") != avant
    finally:
        fichier.write_text(origine, encoding="utf-8")
        app_module._static_versions.clear()
    assert static_version("custom.css") == avant


def test_missing_file_does_not_crash(ctx):
    assert static_version("inexistant.css") == "0"


def test_service_worker_refreshes_in_background():
    """Le cache est servi puis remis à jour, au lieu d'être figé."""
    assert "cache.put(request, response.clone())" in SW
    assert "return cached || reseau" in SW


def test_stylesheet_is_no_longer_precached():
    precache = SW.split("const PRECACHE = [")[1].split("]")[0]
    assert "custom.css" not in precache


def test_cache_name_was_bumped():
    assert "vehicules-static-v4" in SW


def test_old_caches_are_deleted_on_activation():
    assert "caches.delete(k)" in SW
    assert "k !== CACHE_NAME" in SW
