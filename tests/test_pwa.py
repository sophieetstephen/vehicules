"""Installation sur téléphone (PWA) : manifest, icônes, service worker, guide."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from models import db, User

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _setup():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    db.session.remove()
    db.drop_all()
    db.create_all()


def test_manifest_has_png_icons_and_root_scope():
    with open(os.path.join(ROOT, "static", "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["lang"] == "fr"
    sizes = {(i["sizes"], i["purpose"]) for i in manifest["icons"] if i["type"] == "image/png"}
    assert ("192x192", "any") in sizes
    assert ("512x512", "any") in sizes
    assert ("512x512", "maskable") in sizes
    for icon in manifest["icons"]:
        assert os.path.exists(os.path.join(ROOT, icon["src"].lstrip("/"))), icon["src"]


def test_icons_have_expected_dimensions():
    from PIL import Image

    expected = {
        "icon-192.png": 192,
        "icon-512.png": 512,
        "icon-maskable-512.png": 512,
        "apple-touch-icon-180.png": 180,
    }
    for name, size in expected.items():
        with Image.open(os.path.join(ROOT, "static", "icons", name)) as img:
            assert img.size == (size, size), name
    with Image.open(os.path.join(ROOT, "static", "icons", "apple-touch-icon-180.png")) as img:
        assert img.mode == "RGB"  # pas de transparence pour iOS


def test_service_worker_served_at_root_without_login():
    with app.app_context():
        _setup()
        client = app.test_client()
        resp = client.get("/service-worker.js")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("application/javascript")
        assert resp.headers["Service-Worker-Allowed"] == "/"
        assert resp.headers["Cache-Control"] == "no-cache"
        body = resp.data.decode()
        assert "request.mode === 'navigate'" in body
        assert "fetch(request).catch" in body  # les pages ne sont jamais servies depuis le cache
        db.drop_all()


def test_install_guide_public_and_linked():
    with app.app_context():
        _setup()
        client = app.test_client()
        resp = client.get("/installer")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Android (Chrome)" in html and "iPhone / iPad (Safari)" in html
        assert "Sur l'écran d'accueil" in html
        login = client.get("/login").data.decode()
        assert "/installer" in login
        assert 'name="apple-mobile-web-app-capable"' in login
        assert "apple-touch-icon-180.png" in login
        db.drop_all()


def test_logged_in_pages_register_root_service_worker_and_banner():
    with app.app_context():
        _setup()
        u = User(name="Dupont Jean", first_name="Jean", last_name="Dupont", username="dupontj",
                 email="j@ex.fr", role=User.ROLE_USER, status="active", password_hash="x")
        db.session.add(u)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["uid"] = u.id
        html = client.get("/home").data.decode()
        assert "navigator.serviceWorker.register(\"/service-worker.js\", { scope: '/' })" in html
        assert 'id="pwa-banner"' in html
        assert 'name="apple-mobile-web-app-title" content="Véhicules"' in html
        db.drop_all()
