"""Tableau du jour sur l'accueil et annulation d'une réservation par son auteur."""

import importlib
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, has_conflict, today_overview
from models import db, User, Vehicle, Reservation, ReservationSegment, NotificationSettings

app_module = importlib.import_module("app")

NOW = datetime(2026, 9, 18, 10, 0)  # vendredi 18/09/2026, 10h00


@pytest.fixture
def ctx(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    monkeypatch.setattr(app_module, "local_now", lambda: NOW)
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


def _vehicles():
    v1, v2, v3 = Vehicle(code="VL1", label="Léger 1"), Vehicle(code="VL2", label="Léger 2"), Vehicle(code="VRID", label="Rapide")
    db.session.add_all([v1, v2, v3])
    db.session.commit()
    return v1, v2, v3


def _reservation(user, start, end, vehicle=None, status="approved", **kw):
    r = Reservation(user_id=user.id, vehicle_id=vehicle.id if vehicle else None,
                    start_at=start, end_at=end, status=status, **kw)
    db.session.add(r)
    db.session.commit()
    return r


def _capture_mail(monkeypatch):
    calls = []

    def fake(subject, body, to_addrs, *a, **k):
        calls.append({"subject": subject, "body": body, "to": to_addrs if isinstance(to_addrs, str) else list(to_addrs)})
        return True, "sent"

    monkeypatch.setattr(app_module, "send_mail_msmtp", fake)
    return calls


# --- today_overview ---------------------------------------------------------

def test_overview_states_out_later_free(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, v2, v3 = _vehicles()
    _reservation(jean, datetime(2026, 9, 18, 8), datetime(2026, 9, 18, 12), v1, purpose="Formation")   # en cours
    _reservation(jean, datetime(2026, 9, 18, 13), datetime(2026, 9, 18, 17), v2)                       # plus tard
    _reservation(jean, datetime(2026, 9, 17, 8), datetime(2026, 9, 17, 17), v3)                        # hier
    _reservation(jean, datetime(2026, 9, 18, 13), datetime(2026, 9, 18, 17), v3, status="pending")     # pas encore validée

    by_code = {e["vehicle"].code: e for e in today_overview(NOW)}
    assert by_code["VL1"]["state"] == "out"
    assert by_code["VL1"]["current"]["end"] == datetime(2026, 9, 18, 12)
    assert by_code["VL1"]["current"]["reservation"].purpose == "Formation"
    assert by_code["VL2"]["state"] == "later"
    assert by_code["VL2"]["next"]["start"] == datetime(2026, 9, 18, 13)
    assert by_code["VRID"]["state"] == "free"


def test_overview_uses_segments_and_multiday(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, v2, v3 = _vehicles()
    # Réservation segmentée : vendredi sur VL2, sans vehicle_id direct.
    r = _reservation(jean, datetime(2026, 9, 17, 8), datetime(2026, 9, 19, 17))
    db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=v2.id,
                                      start_at=datetime(2026, 9, 18, 0), end_at=datetime(2026, 9, 18, 23, 59)))
    # Réservation sur plusieurs jours directement sur VRID (commencée hier).
    _reservation(jean, datetime(2026, 9, 17, 8), datetime(2026, 9, 20, 17), v3)
    db.session.commit()
    by_code = {e["vehicle"].code: e for e in today_overview(NOW)}
    assert by_code["VL1"]["state"] == "free"
    assert by_code["VL2"]["state"] == "out"
    assert by_code["VRID"]["state"] == "out"
    assert by_code["VRID"]["current"]["end"] == datetime(2026, 9, 20, 17)


def test_overview_ignores_cancelled_and_rejected(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, v2, v3 = _vehicles()
    _reservation(jean, datetime(2026, 9, 18, 8), datetime(2026, 9, 18, 12), v1, status="cancelled")
    _reservation(jean, datetime(2026, 9, 18, 8), datetime(2026, 9, 18, 12), v2, status="rejected")
    assert all(e["state"] == "free" for e in today_overview(NOW))
    assert not has_conflict(v1.id, datetime(2026, 9, 18, 8), datetime(2026, 9, 18, 12))


# --- page d'accueil ---------------------------------------------------------

@pytest.mark.parametrize("role", [User.ROLE_USER, User.ROLE_ADMIN, User.ROLE_SUPERADMIN])
def test_home_shows_overview_and_my_reservations(ctx, role):
    me = _user("Jean", "Dupont", "j@ex.fr", role=role)
    other = _user("Paul", "Martin", "p@ex.fr")
    v1, v2, v3 = _vehicles()
    _reservation(other, datetime(2026, 9, 18, 8), datetime(2026, 9, 18, 12), v1, carpool_with="Luc Bernard")
    mine = _reservation(me, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12), status="pending", purpose="Réunion")
    _reservation(other, datetime(2026, 9, 22, 8), datetime(2026, 9, 22, 12), status="pending")
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = me.id
    html = client.get("/home").data.decode()
    assert "Aujourd'hui" in html
    assert "Sorti" in html and "Paul Martin" in html and "avec Luc Bernard" in html and "jusqu'à 12:00" in html
    assert html.count("Libre") >= 2
    assert "Mes réservations à venir" in html
    assert "21/09/2026" in html and "Réunion" in html
    assert f"/reservation/{mine.id}/cancel" in html
    if role == User.ROLE_USER:
        assert "en attente" not in html.split("Mes réservations")[0]
    else:
        assert "2 demandes en attente" in html


def test_home_without_reservations(ctx):
    me = _user("Jean", "Dupont", "j@ex.fr")
    _vehicles()
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = me.id
    html = client.get("/home").data.decode()
    assert "Aucune réservation à venir" in html
    assert html.count("Libre") == 3


# --- annulation ---------------------------------------------------------------

def test_user_cancels_own_reservation_and_frees_vehicle(ctx, monkeypatch):
    calls = _capture_mail(monkeypatch)
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    db.session.add(NotificationSettings(notify_user_ids=[admin.id]))
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, v2, v3 = _vehicles()
    r = _reservation(jean, datetime(2026, 9, 21, 8), datetime(2026, 9, 22, 17))
    db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=v1.id,
                                      start_at=datetime(2026, 9, 21, 8), end_at=datetime(2026, 9, 21, 23, 59)))
    db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=v2.id,
                                      start_at=datetime(2026, 9, 22, 0), end_at=datetime(2026, 9, 22, 17)))
    db.session.commit()
    assert has_conflict(v1.id, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12))

    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = jean.id
    resp = client.post(f"/reservation/{r.id}/cancel")
    assert resp.status_code == 302

    r = Reservation.query.get(r.id)
    assert r.status == "cancelled"
    assert ReservationSegment.query.filter_by(reservation_id=r.id).count() == 0
    assert not has_conflict(v1.id, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12))
    assert not has_conflict(v2.id, datetime(2026, 9, 22, 8), datetime(2026, 9, 22, 12))

    subjects = {c["subject"]: c for c in calls}
    assert "Réservation annulée par l'utilisateur" in subjects
    assert subjects["Réservation annulée par l'utilisateur"]["to"] == ["chef@ex.fr"]
    assert "VL1, VL2" in subjects["Réservation annulée par l'utilisateur"]["body"]
    assert "Réservation annulée" in subjects
    assert subjects["Réservation annulée"]["to"] == ["j@ex.fr"]

    # Disparaît de "mes réservations", reste visible côté admin avec le badge.
    assert f"/reservation/{r.id}/cancel" not in client.get("/home").data.decode()
    with client.session_transaction() as s:
        s["uid"] = admin.id
    assert "Annulée" in client.get("/admin/reservations").data.decode()


def test_user_cannot_cancel_someone_else_reservation(ctx, monkeypatch):
    _capture_mail(monkeypatch)
    jean = _user("Jean", "Dupont", "j@ex.fr")
    paul = _user("Paul", "Martin", "p@ex.fr")
    v1, *_ = _vehicles()
    r = _reservation(paul, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12), v1)
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = jean.id
    assert client.post(f"/reservation/{r.id}/cancel").status_code == 403
    assert Reservation.query.get(r.id).status == "approved"


def test_cannot_cancel_finished_or_rejected_reservation(ctx, monkeypatch):
    calls = _capture_mail(monkeypatch)
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, *_ = _vehicles()
    finished = _reservation(jean, datetime(2026, 9, 17, 8), datetime(2026, 9, 17, 12), v1)
    rejected = _reservation(jean, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12), status="rejected")
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = jean.id
    assert client.post(f"/reservation/{finished.id}/cancel").status_code == 302
    assert client.post(f"/reservation/{rejected.id}/cancel").status_code == 302
    assert Reservation.query.get(finished.id).status == "approved"
    assert Reservation.query.get(rejected.id).status == "rejected"
    assert calls == []


def test_cancel_requires_login(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, *_ = _vehicles()
    r = _reservation(jean, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12), v1)
    resp = app.test_client().post(f"/reservation/{r.id}/cancel")
    assert resp.status_code == 302 and resp.headers["Location"].startswith("/login")
    assert Reservation.query.get(r.id).status == "approved"
