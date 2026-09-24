"""Attribution d'un véhicule à une partie d'une réservation.

Trois défauts relevés par le second audit, tous reproduits avant correction :

* valider une demande sur B laissait en place le segment posé sur A : A restait
  bloqué pour personne ;
* sur un segment couvrant plusieurs jours, « ce jour » désignait en fait tout
  le segment : supprimer ou changer le 2 agissait aussi sur le 1er et le 3 ;
* un segment ajouté par-dessus un autre donnait deux véhicules en même temps
  à une même réservation.
"""

from datetime import datetime, time

import pytest

from app import app, has_conflict
from models import Reservation, ReservationSegment, User, Vehicle, db


@pytest.fixture
def atelier():
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", TESTING=True,
                      WTF_CSRF_ENABLED=False)
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        chef = User(name="Chef", first_name="C", last_name="Hef", email="chef@ex.fr",
                    role=User.ROLE_ADMIN, password_hash="x", status="active")
        jean = User(name="Jean", first_name="J", last_name="Ean", email="jean@ex.fr",
                    role=User.ROLE_USER, password_hash="x", status="active")
        a = Vehicle(code="A", label="a")
        b = Vehicle(code="B", label="b")
        db.session.add_all([chef, jean, a, b])
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["uid"] = chef.id
            s["pwd_stamp"] = chef.session_stamp(app.config["SECRET_KEY"])
        yield client, jean, a, b
        db.drop_all()


def _reservation(jean, statut="approved", vehicule=None):
    r = Reservation(user_id=jean.id, start_at=datetime(2026, 10, 1, 8),
                    end_at=datetime(2026, 10, 3, 17), status=statut,
                    vehicle_id=vehicule.id if vehicule else None)
    db.session.add(r)
    db.session.commit()
    return r


def _segment(r, vehicule, debut, fin):
    db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=vehicule.id,
                                      start_at=debut, end_at=fin))
    db.session.commit()


def _vehicule_par_jour(r):
    """{jour: {codes des véhicules posés ce jour-là}}"""
    db.session.expire_all()
    jours = {}
    for s in ReservationSegment.query.filter_by(reservation_id=r.id).all():
        jours.setdefault(s.start_at.day, set()).add(s.vehicle.code)
        jours.setdefault(s.end_at.day, set()).add(s.vehicle.code)
    return jours


def _journee(jour):
    return (datetime.combine(datetime(2026, 10, jour).date(), time(9)),
            datetime.combine(datetime(2026, 10, jour).date(), time(10)))


# --- A1 : attribution globale ----------------------------------------------------

def test_whole_assignment_releases_the_previous_segments(atelier):
    client, jean, a, b = atelier
    r = _reservation(jean, statut="pending")
    _segment(r, a, datetime(2026, 10, 1, 8), datetime(2026, 10, 3, 17))

    client.post(f"/admin/manage/{r.id}", data={"action": "approve", "vehicle_id": str(b.id)})

    db.session.expire_all()
    assert db.session.get(Reservation, r.id).vehicle_id == b.id
    assert ReservationSegment.query.filter_by(reservation_id=r.id).count() == 0
    assert not has_conflict(a.id, *_journee(2)), "A reste bloqué pour personne"


# --- A2 : un jour, et seulement ce jour --------------------------------------------

def test_removing_one_day_keeps_the_others(atelier):
    client, jean, a, _ = atelier
    r = _reservation(jean)
    _segment(r, a, datetime(2026, 10, 1, 8), datetime(2026, 10, 3, 17))

    client.post(f"/admin/manage/{r.id}?day=2026-10-02", data={"action": "delete_day"})

    assert _vehicule_par_jour(r) == {1: {"A"}, 3: {"A"}}
    assert has_conflict(a.id, *_journee(1))
    assert not has_conflict(a.id, *_journee(2))
    assert has_conflict(a.id, *_journee(3))


def test_changing_one_day_keeps_the_others(atelier):
    client, jean, a, b = atelier
    r = _reservation(jean)
    _segment(r, a, datetime(2026, 10, 1, 8), datetime(2026, 10, 3, 17))

    client.post(f"/admin/manage/{r.id}?day=2026-10-02",
                data={"action": "segment_day", "vehicle_id": str(b.id)})

    assert _vehicule_par_jour(r) == {1: {"A"}, 2: {"B"}, 3: {"A"}}
    assert not has_conflict(a.id, *_journee(2)), "A est libéré le 2"


def test_leftovers_are_cut_day_by_day(atelier):
    """Chaque jour garde son propre segment : le modifier depuis le planning
    ne touche pas ses voisins."""
    client, jean, a, _ = atelier
    r = _reservation(jean)
    _segment(r, a, datetime(2026, 10, 1, 8), datetime(2026, 10, 3, 17))

    client.post(f"/admin/manage/{r.id}?day=2026-10-03", data={"action": "delete_day"})

    db.session.expire_all()
    segments = ReservationSegment.query.filter_by(reservation_id=r.id).all()
    assert sorted((s.start_at.day, s.end_at.day) for s in segments) == [(1, 1), (2, 2)]


# --- A4 : jamais deux véhicules à la fois -------------------------------------------

def test_a_new_segment_replaces_the_one_already_there(atelier):
    client, jean, a, b = atelier
    r = _reservation(jean)
    for vehicule in (a, b):
        client.post(f"/admin/manage/{r.id}", data={
            "action": "segment", "vehicle_id": str(vehicule.id),
            "start_at": "2026-10-01T08:00", "end_at": "2026-10-01T12:00"})

    db.session.expire_all()
    segments = ReservationSegment.query.filter_by(reservation_id=r.id).all()
    assert [s.vehicle.code for s in segments] == ["B"]
    assert not has_conflict(a.id, datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 10))


def test_segment_on_a_whole_assignment_keeps_the_rest(atelier):
    """Avant, poser B sur une matinée retirait A de tout le reste de la
    réservation."""
    client, jean, a, b = atelier
    r = _reservation(jean, vehicule=a)
    client.post(f"/admin/manage/{r.id}", data={
        "action": "segment", "vehicle_id": str(b.id),
        "start_at": "2026-10-02T08:00", "end_at": "2026-10-02T12:00"})

    assert has_conflict(a.id, *_journee(1))
    assert has_conflict(a.id, datetime(2026, 10, 2, 14), datetime(2026, 10, 2, 15))
    assert not has_conflict(a.id, *_journee(2))
    assert has_conflict(a.id, *_journee(3))
    assert has_conflict(b.id, *_journee(2))


# --- les résidus laissés par l'ancien code -----------------------------------------

def test_old_leftovers_are_found_and_repaired(atelier):
    """La base du Raspberry peut contenir des segments laissés par l'ancienne
    validation : la vérification les signale, la réparation les retire."""
    _, jean, a, b = atelier
    r = _reservation(jean, vehicule=b)
    _segment(r, a, datetime(2026, 10, 1, 8), datetime(2026, 10, 3, 17))
    runner = app.test_cli_runner()

    verification = runner.invoke(args=["check-integrity"])
    assert verification.exit_code == 1
    assert "1 segment(s) resté(s) sur un ancien véhicule" in verification.output

    simulation = runner.invoke(args=["repair-orphan-segments", "--dry-run"])
    assert "passée depuis sur B" in simulation.output
    assert ReservationSegment.query.count() == 1, "la simulation ne supprime rien"

    runner.invoke(args=["repair-orphan-segments"])
    assert ReservationSegment.query.count() == 0
    assert not has_conflict(a.id, *_journee(2))
    assert has_conflict(b.id, *_journee(2)), "l'attribution réelle reste"
    assert runner.invoke(args=["check-integrity"]).exit_code == 0
