"""Limitation des tentatives de connexion (blocage temporaire après échecs)."""

from datetime import datetime, timedelta

import pytest

from app import app, login_blocked_minutes
from models import db, User, LoginAttempt

PASSWORD = "Kx7m-Rp2v-Q9wT"


@pytest.fixture
def ctx():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["LOGIN_MAX_ATTEMPTS"] = 5
    app.config["LOGIN_LOCKOUT_MINUTES"] = 15
    app.config["LOGIN_IP_MAX_ATTEMPTS"] = 30
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        u = User(name="Dupont Jean", first_name="Jean", last_name="Dupont", username="dupontj",
                 email="j@ex.fr", role=User.ROLE_USER, status="active")
        u.set_password(PASSWORD)
        db.session.add(u)
        db.session.commit()
        yield u
        db.drop_all()


def _login(client, username, password, ip="10.0.0.1"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        headers={"X-Forwarded-For": ip},
    )


def test_lockout_after_five_failures_even_with_correct_password(ctx):
    client = app.test_client()
    for _ in range(5):
        resp = _login(client, "dupontj", "mauvais")
        assert resp.status_code == 200 and "Identifiants invalides" in resp.data.decode()
    assert LoginAttempt.query.filter_by(username="dupontj", success=False).count() == 5

    resp = _login(client, "DupontJ", PASSWORD)  # bon mot de passe, mais bloqué
    assert resp.status_code == 429
    html = resp.data.decode()
    assert "Trop de tentatives" in html and "15 minutes" in html
    with client.session_transaction() as s:
        assert "uid" not in s
    # Une tentative pendant le blocage n'est pas comptée.
    assert LoginAttempt.query.filter_by(username="dupontj").count() == 5


def test_lock_expires_after_window(ctx):
    client = app.test_client()
    for _ in range(5):
        _login(client, "dupontj", "mauvais")
    assert login_blocked_minutes("dupontj", "10.0.0.1") == 15
    # 16 minutes plus tard : les échecs sont hors fenêtre.
    for a in LoginAttempt.query.all():
        a.created_at = datetime.utcnow() - timedelta(minutes=16)
    db.session.commit()
    assert login_blocked_minutes("dupontj", "10.0.0.1") == 0
    resp = _login(client, "dupontj", PASSWORD)
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert s["uid"] == ctx.id


def test_remaining_minutes_decrease(ctx):
    client = app.test_client()
    for _ in range(5):
        _login(client, "dupontj", "mauvais")
    for a in LoginAttempt.query.all():
        a.created_at = datetime.utcnow() - timedelta(minutes=10, seconds=30)
    db.session.commit()
    assert login_blocked_minutes("dupontj", None) == 5


def test_success_resets_failure_counter(ctx):
    client = app.test_client()
    for _ in range(4):
        _login(client, "dupontj", "mauvais")
    resp = _login(client, "dupontj", PASSWORD)
    assert resp.status_code == 302
    assert LoginAttempt.query.filter_by(username="dupontj", success=False).count() == 0
    assert LoginAttempt.query.filter_by(username="dupontj", success=True).count() == 1
    client.get("/logout")
    for _ in range(4):
        _login(client, "dupontj", "mauvais")
    assert _login(client, "dupontj", PASSWORD).status_code == 302


def test_unknown_identifier_is_locked_too_without_revealing_it(ctx):
    client = app.test_client()
    for _ in range(5):
        resp = _login(client, "inconnu", "x")
        assert "Identifiants invalides" in resp.data.decode()
    assert _login(client, "inconnu", "x").status_code == 429


def test_lock_is_per_identifier(ctx):
    client = app.test_client()
    for _ in range(5):
        _login(client, "autre", "x")
    assert _login(client, "dupontj", PASSWORD).status_code == 302


def test_ip_lockout_across_identifiers(ctx):
    app.config["LOGIN_IP_MAX_ATTEMPTS"] = 8
    client = app.test_client()
    for i in range(8):
        _login(client, f"compte{i}", "x", ip="203.0.113.7")
    # Même IP : bloquée quel que soit l'identifiant, même valide.
    assert _login(client, "dupontj", PASSWORD, ip="203.0.113.7").status_code == 429
    # Autre IP : pas concernée.
    assert _login(client, "dupontj", PASSWORD, ip="203.0.113.8").status_code == 302


def test_client_ip_is_the_one_seen_by_the_proxy(ctx):
    """Chaque proxy ajoute à X-Forwarded-For l'adresse qu'il a vue. Avec Caddy
    seul devant l'application, c'est la dernière valeur qui est fiable ; les
    précédentes viennent du client."""
    client = app.test_client()
    _login(client, "dupontj", "x", ip="198.51.100.4, 10.0.0.2")
    assert LoginAttempt.query.first().ip == "10.0.0.2"
    client.post("/login", data={"username": "dupontj", "password": "x"},
                environ_base={"REMOTE_ADDR": "192.0.2.9"})
    assert LoginAttempt.query.order_by(LoginAttempt.id.desc()).first().ip == "192.0.2.9"


def test_forged_address_cannot_dodge_the_ip_limit(ctx):
    """On retenait la première valeur, que le client écrit lui-même : en en
    changeant à chaque essai, il échappait à la limite par adresse."""
    client = app.test_client()
    for n in range(3):
        _login(client, "dupontj", "x", ip=f"203.0.113.{n}, 192.0.2.50")
    adresses = {a.ip for a in LoginAttempt.query.all()}
    assert adresses == {"192.0.2.50"}, "une seule adresse réelle derrière les faux"


def test_old_attempts_are_purged(ctx):
    db.session.add(LoginAttempt(username="vieux", ip="1.1.1.1", success=False,
                                created_at=datetime.utcnow() - timedelta(days=31)))
    db.session.commit()
    _login(app.test_client(), "dupontj", "x")
    assert LoginAttempt.query.filter_by(username="vieux").count() == 0
