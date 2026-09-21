"""Échecs d'e-mail signalés, et pas de double attribution entre administrateurs."""

import html as html_lib
import importlib
import logging
from datetime import datetime

import pytest

from app import app, commit_if_still_free
from models import db, User, Vehicle, Reservation, ReservationSegment, NotificationSettings

app_module = importlib.import_module("app")
CRENEAU = (datetime(2026, 5, 4, 8), datetime(2026, 5, 4, 12))


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


def _user(first, last, email, role=User.ROLE_USER):
    u = User(name=f"{last} {first}", first_name=first, last_name=last, email=email,
             role=role, status="active", password_hash="x")
    db.session.add(u)
    db.session.flush()
    u.assign_username()
    db.session.commit()
    return u


def _client(user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = user.id
        s["pwd_stamp"] = user.session_stamp(app.config["SECRET_KEY"])
    return c


def _texte(reponse):
    """Texte de la page, entités HTML décodées (Jinja échappe les apostrophes)."""
    return html_lib.unescape(reponse.data.decode())


def _reservation(user, vehicle=None, status="pending"):
    r = Reservation(user_id=user.id, vehicle_id=vehicle.id if vehicle else None,
                    start_at=CRENEAU[0], end_at=CRENEAU[1], status=status)
    db.session.add(r)
    db.session.commit()
    return r


# --- les échecs d'envoi ne sont plus silencieux -----------------------------

def test_smtp_failure_is_logged_and_shown(ctx, monkeypatch, caplog):
    """send_mail_msmtp renvoie (False, ...) au lieu de lever : c'était invisible."""
    monkeypatch.setattr(app_module, "send_mail_msmtp",
                        lambda *a, **k: (False, "smtp error: connection refused"))
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    v = Vehicle(code="VL1", label="Léger 1")
    db.session.add(v)
    db.session.commit()
    r = _reservation(jean)

    with caplog.at_level(logging.ERROR):
        resp = _client(admin).post(f"/admin/manage/{r.id}",
                                   data={"action": "approve", "vehicle_id": v.id},
                                   follow_redirects=True)

    html = _texte(resp)
    assert "n'a pas pu être envoyé" in html, "l'admin doit être averti"
    assert "jean@ex.fr" in html
    assert "Echec d'envoi" in caplog.text
    assert "connection refused" in caplog.text
    # L'action métier a bien eu lieu malgré l'échec d'e-mail.
    assert db.session.get(Reservation, r.id).status == "approved"


def test_exception_during_send_is_caught_and_signalled(ctx, monkeypatch, caplog):
    def explose(*a, **k):
        raise OSError("réseau injoignable")

    monkeypatch.setattr(app_module, "send_mail_msmtp", explose)
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    v = Vehicle(code="VL1", label="Léger 1")
    db.session.add(v)
    db.session.commit()
    r = _reservation(jean)
    with caplog.at_level(logging.ERROR):
        resp = _client(admin).post(f"/admin/manage/{r.id}",
                                   data={"action": "approve", "vehicle_id": v.id},
                                   follow_redirects=True)
    assert "n'a pas pu être envoyé" in _texte(resp)
    assert "Echec d'envoi" in caplog.text
    assert db.session.get(Reservation, r.id).status == "approved"


def test_successful_send_is_silent(ctx, monkeypatch):
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    v = Vehicle(code="VL1", label="Léger 1")
    db.session.add(v)
    db.session.commit()
    r = _reservation(jean)
    resp = _client(admin).post(f"/admin/manage/{r.id}",
                               data={"action": "approve", "vehicle_id": v.id},
                               follow_redirects=True)
    assert "n'a pas pu être envoyé" not in _texte(resp)


@pytest.mark.parametrize("retour,attendu", [
    (None, True), (True, True), ((True, "sent"), True), (False, False),
    ((False, "smtp error"), False), ((), True),
])
def test_mail_result_interpretation(retour, attendu):
    """Les doublures de test renvoient des formes variées : toutes tolérées."""
    assert app_module._mail_result_ok(retour)[0] is attendu


def test_notify_without_recipients_does_nothing(ctx, monkeypatch):
    appels = []
    monkeypatch.setattr(app_module, "send_mail_msmtp",
                        lambda *a, **k: appels.append(a) or (True, "sent"))
    assert app_module.notify("Sujet", "Corps", []) is True
    assert appels == []


# --- deux administrateurs valident en même temps ----------------------------

def test_second_admin_cannot_double_book(ctx, monkeypatch):
    """Le véhicule est libre à la vérification, pris au moment d'enregistrer."""
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    v = Vehicle(code="VL1", label="Léger 1")
    db.session.add(v)
    db.session.commit()
    r = _reservation(jean)

    vrai = app_module.has_conflict
    etat = {"appels": 0}

    def has_conflict_course(*a, **k):
        etat["appels"] += 1
        if etat["appels"] == 1:
            return False          # vérification initiale : libre
        return True               # au moment d'enregistrer : déjà pris

    monkeypatch.setattr(app_module, "has_conflict", has_conflict_course)
    resp = _client(admin).post(f"/admin/manage/{r.id}",
                               data={"action": "approve", "vehicle_id": v.id},
                               follow_redirects=True)

    assert "vient d'être attribué par un autre" in _texte(resp)
    monkeypatch.setattr(app_module, "has_conflict", vrai)
    rafraichie = db.session.get(Reservation, r.id)
    assert rafraichie.status == "pending", "la réservation ne doit pas être validée"
    assert rafraichie.vehicle_id is None, "aucun véhicule ne doit être attribué"


def test_second_admin_cannot_double_book_a_segment(ctx, monkeypatch):
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    v = Vehicle(code="VL1", label="Léger 1")
    db.session.add(v)
    db.session.commit()
    r = _reservation(jean)

    etat = {"appels": 0}

    def has_conflict_course(*a, **k):
        etat["appels"] += 1
        return etat["appels"] != 1

    monkeypatch.setattr(app_module, "has_conflict", has_conflict_course)
    resp = _client(admin).post(f"/admin/manage/{r.id}", data={
        "action": "segment", "vehicle_id": v.id,
        "start_at": CRENEAU[0].isoformat(), "end_at": CRENEAU[1].isoformat(),
    }, follow_redirects=True)

    assert "vient d'être attribué par un autre" in _texte(resp)
    assert ReservationSegment.query.count() == 0, "aucun segment ne doit rester"


def test_normal_approval_still_works(ctx, monkeypatch):
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    v = Vehicle(code="VL1", label="Léger 1")
    db.session.add(v)
    db.session.commit()
    r = _reservation(jean)
    resp = _client(admin).post(f"/admin/manage/{r.id}",
                               data={"action": "approve", "vehicle_id": v.id},
                               follow_redirects=True)
    assert "Demande approuvée" in _texte(resp)
    rafraichie = db.session.get(Reservation, r.id)
    assert rafraichie.status == "approved" and rafraichie.vehicle_id == v.id


def test_commit_if_still_free_rolls_back_cleanly(ctx, monkeypatch):
    jean = _user("Jean", "Dupont", "jean@ex.fr")
    v = Vehicle(code="VL1", label="Léger 1")
    db.session.add(v)
    db.session.commit()
    r = _reservation(jean)

    monkeypatch.setattr(app_module, "has_conflict", lambda *a, **k: True)
    r.vehicle_id = v.id
    r.status = "approved"
    assert commit_if_still_free(v.id, *CRENEAU, r.id) is False
    # Rien ne doit subsister de la tentative.
    rafraichie = db.session.get(Reservation, r.id)
    assert rafraichie.status == "pending" and rafraichie.vehicle_id is None
