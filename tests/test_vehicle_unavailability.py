"""Indisponibilité d'un véhicule (panne, entretien…) déclarée par un admin."""

import importlib
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, has_conflict, today_overview
from models import db, User, Vehicle, Reservation, ReservationSegment, VehicleUnavailability

app_module = importlib.import_module("app")

NOW = datetime(2026, 9, 18, 10, 0)


@pytest.fixture
def ctx(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    monkeypatch.setattr(app_module, "local_now", lambda: NOW)
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
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
    v1, v2 = Vehicle(code="VL1", label="Léger 1"), Vehicle(code="VL2", label="Léger 2")
    db.session.add_all([v1, v2])
    db.session.commit()
    return v1, v2


def _unav(vehicle, start, end=None, category="mecanique", details=None):
    u = VehicleUnavailability(vehicle_id=vehicle.id, start_at=start, end_at=end, category=category, details=details)
    db.session.add(u)
    db.session.commit()
    return u


def _client_as(user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = user.id
        s["pwd_stamp"] = user.session_stamp(app.config["SECRET_KEY"])
    return c


# --- blocage des attributions ---------------------------------------------

def test_unavailability_blocks_vehicle_only_on_its_period(ctx):
    v1, v2 = _vehicles()
    _unav(v1, datetime(2026, 9, 20), datetime(2026, 9, 22, 23, 59, 59), details="embrayage")
    assert has_conflict(v1.id, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12))
    assert has_conflict(v1.id, datetime(2026, 9, 22, 13), datetime(2026, 9, 22, 17))
    assert not has_conflict(v1.id, datetime(2026, 9, 23, 8), datetime(2026, 9, 23, 12))
    assert not has_conflict(v1.id, datetime(2026, 9, 19, 8), datetime(2026, 9, 19, 12))
    assert not has_conflict(v2.id, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12))


def test_open_ended_unavailability_blocks_forever(ctx):
    v1, _ = _vehicles()
    _unav(v1, datetime(2026, 9, 18))
    assert has_conflict(v1.id, datetime(2030, 1, 1, 8), datetime(2030, 1, 1, 12))
    assert not has_conflict(v1.id, datetime(2026, 9, 17, 8), datetime(2026, 9, 17, 12))


def test_admin_cannot_approve_reservation_on_unavailable_vehicle(ctx):
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, v2 = _vehicles()
    _unav(v1, datetime(2026, 9, 21), datetime(2026, 9, 21, 23, 59, 59))
    r = Reservation(user_id=jean.id, start_at=datetime(2026, 9, 21, 8), end_at=datetime(2026, 9, 21, 12), status="pending")
    db.session.add(r)
    db.session.commit()
    c = _client_as(admin)
    page = c.get(f"/admin/manage/{r.id}").data.decode()
    assert "Indisponible" in page
    c.post(f"/admin/manage/{r.id}", data={"action": "approve", "vehicle_id": v1.id})
    assert db.session.get(Reservation, r.id).status == "pending"
    c.post(f"/admin/manage/{r.id}", data={"action": "approve", "vehicle_id": v2.id})
    assert db.session.get(Reservation, r.id).status == "approved"


# --- accueil et planning ------------------------------------------------------

def test_today_overview_shows_unavailable_before_reservations(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, v2 = _vehicles()
    db.session.add(Reservation(user_id=jean.id, vehicle_id=v1.id, start_at=datetime(2026, 9, 18, 8),
                               end_at=datetime(2026, 9, 18, 12), status="approved"))
    db.session.commit()
    _unav(v1, datetime(2026, 9, 18), datetime(2026, 9, 25, 23, 59, 59), category="entretien", details="CT")
    by_code = {e["vehicle"].code: e for e in today_overview(NOW)}
    assert by_code["VL1"]["state"] == "unavailable"
    assert by_code["VL1"]["unavailability"].label == "Entretien / contrôle technique – CT"
    assert by_code["VL2"]["state"] == "free"

    c = _client_as(jean)
    html = c.get("/home").data.decode()
    assert "Indisponible" in html and "contrôle technique – CT" in html and "jusqu'au 25/09" in html


def test_calendar_shows_unavailability(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    _unav(v1, datetime(2026, 9, 20), None, details="moteur")
    html = _client_as(jean).get("/calendar/month?y=2026&m=9").data.decode()
    assert "Indispo." in html and "moteur" in html
    html_before = _client_as(jean).get("/calendar/month?y=2026&m=8").data.decode()
    assert "Indispo." not in html_before


# --- administration ----------------------------------------------------------

def test_admin_declares_and_lifts_unavailability(ctx):
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    # Une réservation validée utilise déjà VL1 sur la période : l'admin doit être prévenu.
    r = Reservation(user_id=jean.id, vehicle_id=v1.id, start_at=datetime(2026, 9, 22, 8),
                    end_at=datetime(2026, 9, 22, 12), status="approved", purpose="Formation")
    db.session.add(r)
    db.session.commit()

    c = _client_as(admin)
    assert c.get(f"/admin/vehicles/{v1.id}/unavailability").status_code == 200
    resp = c.post(
        f"/admin/vehicles/{v1.id}/unavailability",
        data={"start_date": "2026-09-20", "end_date": "2026-09-25", "category": "mecanique", "details": "Embrayage"},
        follow_redirects=True,
    )
    html = resp.data.decode()
    assert "Indisponibilité enregistrée" in html
    assert "1 réservation(s) validée(s) utilisent VL1" in html
    assert "Formation" in html and f"/admin/manage/{r.id}" in html
    unav = VehicleUnavailability.query.one()
    assert unav.vehicle_id == v1.id and unav.created_by == admin.id
    assert unav.start_at == datetime(2026, 9, 20) and unav.end_at.date() == datetime(2026, 9, 25).date()
    assert unav.label == "Panne mécanique – Embrayage"

    # Le parc affiche le badge quand l'indisponibilité est en cours.
    unav.start_at = datetime(2026, 9, 18)
    db.session.commit()
    assert "Indisponible" in c.get("/admin/vehicles").data.decode()

    resp = c.post(f"/admin/vehicles/unavailability/{unav.id}/delete", follow_redirects=True)
    assert "peut de nouveau être attribué" in resp.data.decode()
    assert VehicleUnavailability.query.count() == 0
    assert not has_conflict(v1.id, datetime(2026, 9, 21, 8), datetime(2026, 9, 21, 12))


def test_end_before_start_is_rejected(ctx):
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    v1, _ = _vehicles()
    resp = _client_as(admin).post(
        f"/admin/vehicles/{v1.id}/unavailability",
        data={"start_date": "2026-09-25", "end_date": "2026-09-20", "category": "autre", "details": ""},
    )
    assert resp.status_code == 200
    assert "postérieure à la date de début" in resp.data.decode()
    assert VehicleUnavailability.query.count() == 0


def test_simple_user_cannot_manage_unavailability(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    c = _client_as(jean)
    assert c.get(f"/admin/vehicles/{v1.id}/unavailability").status_code == 403
    assert c.post(f"/admin/vehicles/{v1.id}/unavailability",
                  data={"start_date": "2026-09-20", "category": "autre"}).status_code == 403
    assert VehicleUnavailability.query.count() == 0


def test_deleting_vehicle_removes_its_unavailabilities(ctx):
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_SUPERADMIN)
    v1, _ = _vehicles()
    _unav(v1, datetime(2026, 9, 20))
    _client_as(admin).post(f"/admin/vehicles/{v1.id}/delete")
    assert db.session.get(Vehicle, v1.id) is None
    assert VehicleUnavailability.query.count() == 0
