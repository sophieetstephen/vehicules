"""Aucune suppression ne doit laisser de segment orphelin.

Un segment orphelin est invisible au planning (jointure sur Reservation) mais
reste vu par ``has_conflict`` : le véhicule apparaîtrait libre tout en étant
impossible à attribuer.
"""

import contextlib
from datetime import datetime, timedelta

import pytest

from app import (
    app,
    delete_reservations,
    find_orphan_segments,
    has_conflict,
    purge_expired_requests,
    purge_archived_reservations,
)
from models import db, User, Vehicle, Reservation, ReservationSegment

FUTUR = (datetime(2027, 6, 1, 8), datetime(2027, 6, 1, 12))


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


@contextlib.contextmanager
def _comme_avant():
    """Fabriquer des données comme les laissait l'ancien code.

    Les clés étrangères sont désormais actives : une suppression brute qui
    laisserait un segment sans réservation est refusée par SQLite. C'est
    précisément la protection voulue — pour reproduire les données d'époque,
    on les coupe le temps de la manipulation. La consigne n'a d'effet qu'hors
    transaction, d'où le commit préalable.
    """
    db.session.commit()
    db.session.execute(db.text("PRAGMA foreign_keys=OFF"))
    try:
        yield
        db.session.commit()
    finally:
        db.session.execute(db.text("PRAGMA foreign_keys=ON"))


def _user(role=User.ROLE_USER, email="j@ex.fr", username=None):
    u = User(name="Dupont Jean", first_name="Jean", last_name="Dupont",
             username=username or email.split("@")[0], email=email, role=role,
             status="active", password_hash="x")
    db.session.add(u)
    db.session.commit()
    return u


def _vehicle(code="VL1"):
    v = Vehicle(code=code, label=f"Véhicule {code}")
    db.session.add(v)
    db.session.commit()
    return v


def _reservation_with_segment(user, vehicle, status="pending", end_at=None, archived_at=None):
    """Réservation dont le segment occupe un créneau lointain (FUTUR)."""
    r = Reservation(
        user_id=user.id,
        start_at=datetime.utcnow() - timedelta(days=10),
        end_at=end_at or datetime.utcnow() - timedelta(days=9),
        status=status,
        archived_at=archived_at,
    )
    db.session.add(r)
    db.session.commit()
    db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=vehicle.id,
                                      start_at=FUTUR[0], end_at=FUTUR[1]))
    db.session.commit()
    return r


def _client(user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = user.id
        s["pwd_stamp"] = user.session_stamp(app.config["SECRET_KEY"])
    return c


# --- les trois sources d'orphelins -------------------------------------------

def test_nightly_purge_removes_segments(ctx):
    """Cas le plus grave : la purge tourne automatiquement chaque nuit."""
    u = _user()
    v = _vehicle()
    _reservation_with_segment(u, v, status="pending")
    assert has_conflict(v.id, *FUTUR)

    purge_expired_requests()

    assert Reservation.query.count() == 0
    assert ReservationSegment.query.count() == 0
    assert not has_conflict(v.id, *FUTUR), "le véhicule reste bloqué par un fantôme"
    assert find_orphan_segments() == []


def test_archived_purge_removes_segments(ctx):
    u = _user()
    v = _vehicle()
    _reservation_with_segment(u, v, status="approved",
                              archived_at=datetime.utcnow() - timedelta(days=200))
    purge_archived_reservations()
    assert Reservation.query.count() == 0
    assert ReservationSegment.query.count() == 0
    assert not has_conflict(v.id, *FUTUR)


def test_deleting_user_removes_segments(ctx):
    admin = _user(role=User.ROLE_SUPERADMIN, email="chef@ex.fr")
    u = _user()
    v = _vehicle()
    _reservation_with_segment(u, v, status="approved")
    _client(admin).post(f"/admin/delete/{u.id}")
    assert db.session.get(User, u.id) is None
    assert Reservation.query.count() == 0
    assert ReservationSegment.query.count() == 0
    assert not has_conflict(v.id, *FUTUR)


# --- suppression d'un véhicule -----------------------------------------------

def test_vehicle_in_use_cannot_be_deleted(ctx):
    admin = _user(role=User.ROLE_SUPERADMIN, email="chef@ex.fr")
    u = _user()
    v = _vehicle()
    _reservation_with_segment(u, v, status="approved")
    resp = _client(admin).post(f"/admin/vehicles/{v.id}/delete", follow_redirects=True)
    html = resp.data.decode()
    assert "Impossible de supprimer VL1" in html
    assert "indisponible" in html
    assert db.session.get(Vehicle, v.id) is not None
    assert ReservationSegment.query.count() == 1


def test_vehicle_used_by_reservation_only_cannot_be_deleted(ctx):
    admin = _user(role=User.ROLE_SUPERADMIN, email="chef@ex.fr")
    u = _user()
    v = _vehicle()
    db.session.add(Reservation(user_id=u.id, vehicle_id=v.id, start_at=FUTUR[0],
                               end_at=FUTUR[1], status="approved"))
    db.session.commit()
    _client(admin).post(f"/admin/vehicles/{v.id}/delete")
    assert db.session.get(Vehicle, v.id) is not None


def test_unused_vehicle_can_still_be_deleted(ctx):
    admin = _user(role=User.ROLE_SUPERADMIN, email="chef@ex.fr")
    v = _vehicle("VL9")
    resp = _client(admin).post(f"/admin/vehicles/{v.id}/delete", follow_redirects=True)
    assert "Véhicule supprimé" in resp.data.decode()
    assert db.session.get(Vehicle, v.id) is None


# --- réparation de l'existant -------------------------------------------------

def test_find_and_repair_existing_orphans(ctx):
    u = _user()
    v, v2 = _vehicle(), _vehicle("VL2")
    r = _reservation_with_segment(u, v, status="approved")
    # Fantômes fabriqués comme le faisait l'ancien code : suppression brute.
    with _comme_avant():
        Reservation.query.filter_by(id=r.id).delete(synchronize_session=False)
    db.session.commit()
    orphelin_reservation = ReservationSegment.query.one()

    seg2 = ReservationSegment(reservation_id=orphelin_reservation.id, vehicle_id=v2.id,
                              start_at=FUTUR[0], end_at=FUTUR[1])
    with _comme_avant():
        db.session.add(seg2)
    with _comme_avant():
        Vehicle.query.filter_by(id=v2.id).delete(synchronize_session=False)
    db.session.commit()

    orphans = find_orphan_segments()
    assert len(orphans) == 2
    # Un fantôme bloquait le véhicule. Depuis que l'occupation se lit à travers
    # la réservation (et son statut), un segment sans réservation ne bloque
    # plus rien, même avant réparation.
    assert not has_conflict(v.id, *FUTUR), "un fantôme ne doit plus bloquer"

    runner = app.test_cli_runner()
    simulation = runner.invoke(args=["repair-orphan-segments", "--dry-run"])
    assert "2 segment(s)" in simulation.output
    assert ReservationSegment.query.count() == 2, "la simulation ne supprime rien"

    resultat = runner.invoke(args=["repair-orphan-segments"])
    assert "2 segment(s) fantôme(s) supprimé(s)" in resultat.output
    assert ReservationSegment.query.count() == 0
    assert not has_conflict(v.id, *FUTUR)

    assert "Aucun segment fantôme" in runner.invoke(args=["repair-orphan-segments"]).output


def test_repair_detaches_reservation_from_deleted_vehicle(ctx):
    u = _user()
    v = _vehicle()
    r = Reservation(user_id=u.id, vehicle_id=v.id, start_at=FUTUR[0], end_at=FUTUR[1],
                    status="approved")
    db.session.add(r)
    db.session.commit()
    with _comme_avant():
        Vehicle.query.filter_by(id=v.id).delete(synchronize_session=False)
    db.session.commit()

    out = app.test_cli_runner().invoke(args=["repair-orphan-segments"]).output
    assert "1 réservation(s) détachée(s)" in out
    assert db.session.get(Reservation, r.id).vehicle_id is None


# --- helper ---------------------------------------------------------------------

def test_delete_reservations_handles_many_rows(ctx):
    """Le découpage par lots évite la limite de paramètres de SQLite."""
    u = _user()
    v = _vehicle()
    for i in range(1000):
        r = Reservation(user_id=u.id, start_at=datetime(2027, 1, 1, 8),
                        end_at=datetime(2027, 1, 1, 12), status="pending")
        db.session.add(r)
        db.session.flush()
        db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=v.id,
                                          start_at=datetime(2027, 1, 1, 8),
                                          end_at=datetime(2027, 1, 1, 12)))
    db.session.commit()
    assert delete_reservations(Reservation.query) == 1000
    db.session.commit()
    assert Reservation.query.count() == 0
    assert ReservationSegment.query.count() == 0


def test_delete_reservations_on_empty_query(ctx):
    assert delete_reservations(Reservation.query) == 0
