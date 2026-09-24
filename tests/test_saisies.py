"""Saisies refusées par un message, pas par une page d'erreur 500.

Relevé par le second audit, reproduit avant correction :

* une date envoyée avec un fuseau horaire ne pouvait pas être comparée aux
  réservations, enregistrées sans fuseau ;
* un code de véhicule déjà pris faisait échouer l'enregistrement ;
* une adresse e-mail déjà prise aussi, à la modification d'un utilisateur
  (la création la vérifiait déjà).
"""

import html
from datetime import datetime

import pytest

from app import app
from models import Reservation, ReservationSegment, User, Vehicle, db


@pytest.fixture
def atelier():
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", TESTING=True,
                      WTF_CSRF_ENABLED=False, PROPAGATE_EXCEPTIONS=False)
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        chef = User(name="Chef", first_name="C", last_name="Hef", email="chef@ex.fr",
                    role=User.ROLE_SUPERADMIN, password_hash="x", status="active")
        jean = User(name="Jean", first_name="Jean", last_name="X", email="jean@ex.fr",
                    role=User.ROLE_USER, password_hash="x", status="active")
        vl1 = Vehicle(code="VL1", label="Chef")
        vpt = Vehicle(code="VPT", label="9 places")
        db.session.add_all([chef, jean, vl1, vpt])
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["uid"] = chef.id
            s["pwd_stamp"] = chef.session_stamp(app.config["SECRET_KEY"])
        yield client, jean, vl1, vpt
        db.drop_all()
    app.config["PROPAGATE_EXCEPTIONS"] = None


def _texte(reponse):
    return html.unescape(reponse.data.decode())


# --- dates avec fuseau ---------------------------------------------------------------

def test_date_with_timezone_is_read_as_local_time(atelier):
    client, jean, vl1, _ = atelier
    r = Reservation(user_id=jean.id, start_at=datetime(2026, 10, 1, 8),
                    end_at=datetime(2026, 10, 1, 17), status="approved")
    db.session.add(r)
    db.session.commit()

    # 06:00 UTC, c'est 08:00 à Paris en octobre (heure d'été).
    reponse = client.post(f"/admin/manage/{r.id}", data={
        "action": "segment", "vehicle_id": str(vl1.id),
        "start_at": "2026-10-01T06:00+00:00", "end_at": "2026-10-01T12:00+02:00"})

    assert reponse.status_code == 302
    seg = ReservationSegment.query.one()
    assert (seg.start_at, seg.end_at) == (datetime(2026, 10, 1, 8), datetime(2026, 10, 1, 12))
    assert seg.start_at.tzinfo is None


# --- code de véhicule déjà pris --------------------------------------------------------

def test_new_vehicle_with_a_taken_code_is_refused(atelier):
    client, *_ = atelier
    reponse = client.post("/admin/vehicles/new",
                          data={"code": "vl1", "label": "Doublon", "category": ""})
    assert reponse.status_code == 400
    page = _texte(reponse)
    assert "Le code « VL1 » est déjà utilisé" in page
    assert 'value="Doublon"' in page, "la saisie est conservée"
    assert Vehicle.query.count() == 2


def test_renaming_to_a_taken_code_is_refused(atelier):
    client, _, vl1, vpt = atelier
    reponse = client.post(f"/admin/vehicles/{vpt.id}/edit",
                          data={"code": "VL1", "label": "9 places", "category": ""})
    assert reponse.status_code == 400
    assert "déjà utilisé" in _texte(reponse)
    db.session.expire_all()
    assert db.session.get(Vehicle, vpt.id).code == "VPT"


def test_keeping_its_own_code_is_accepted(atelier):
    client, _, vl1, _ = atelier
    reponse = client.post(f"/admin/vehicles/{vl1.id}/edit",
                          data={"code": "VL1", "label": "Chef de centre", "category": ""})
    assert reponse.status_code == 302
    db.session.expire_all()
    assert db.session.get(Vehicle, vl1.id).label == "Chef de centre"


# --- adresse e-mail déjà prise ---------------------------------------------------------

def test_editing_a_user_with_a_taken_email_is_refused(atelier):
    client, jean, *_ = atelier
    reponse = client.post(f"/admin/user/{jean.id}/edit", data={
        "first_name": "Jean", "last_name": "X", "email": "CHEF@ex.fr", "role": "user"})
    assert reponse.status_code == 200
    assert "Cette adresse e-mail est déjà utilisée." in _texte(reponse)
    db.session.expire_all()
    assert db.session.get(User, jean.id).email == "jean@ex.fr"


def test_editing_a_user_keeping_its_own_email_works(atelier):
    client, jean, *_ = atelier
    reponse = client.post(f"/admin/user/{jean.id}/edit", data={
        "first_name": "Jean-Pierre", "last_name": "X", "email": "jean@ex.fr", "role": "user"})
    assert reponse.status_code == 302
    db.session.expire_all()
    assert db.session.get(User, jean.id).first_name == "Jean-Pierre"
