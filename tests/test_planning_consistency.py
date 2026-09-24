"""Cohérence du planning : occupation, segments, références, adresses.

Audit du 24/09/2026, reproduit : refuser une demande découpée laissait le
véhicule bloqué ; un segment dont la fin précédait le début était accepté ; un
mois 13 dans l'adresse levait une erreur 500 ; les clés étrangères SQLite
étaient désactivées. Trouvé en corrigeant : un jour hors de la réservation
dans l'adresse fabriquait un segment inversé, un véhicule absent du formulaire
levait une erreur 500, et trois chemins d'attribution échappaient à la
revérification contre les doubles réservations.
"""

import importlib
from datetime import datetime

import pytest

from app import app, has_conflict, segment_period_error
from models import (db, User, Vehicle, Reservation, ReservationSegment,
                    VehicleUnavailability, CredentialHandoff)

app_module = importlib.import_module("app")

LUNDI = datetime(2026, 10, 5, 8)
MARDI_SOIR = datetime(2026, 10, 6, 17)


@pytest.fixture
def ctx(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.drop_all()


def _user(prenom="Jean", role=User.ROLE_USER):
    u = User(name=f"X {prenom}", first_name=prenom, last_name="X",
             email=f"{prenom.lower()}@ex.fr", role=role, status="active", password_hash="x")
    db.session.add(u)
    db.session.flush()
    u.assign_username()
    db.session.commit()
    return u


def _client(u):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = u.id
        s["pwd_stamp"] = u.session_stamp(app.config["SECRET_KEY"])
    return c


@pytest.fixture
def parc(ctx):
    v1, v2 = Vehicle(code="VL1", label="a"), Vehicle(code="VL2", label="b")
    db.session.add_all([v1, v2])
    db.session.commit()
    return {"jean": _user(), "chef": _user("Chef", User.ROLE_SUPERADMIN), "v1": v1, "v2": v2}


def _reservation(parc, statut="approved", vehicule=None):
    r = Reservation(user_id=parc["jean"].id, vehicle_id=vehicule.id if vehicule else None,
                    start_at=LUNDI, end_at=MARDI_SOIR, status=statut, purpose="Stage")
    db.session.add(r)
    db.session.commit()
    return r


def _segment(r, vehicule, debut=LUNDI, fin=datetime(2026, 10, 5, 17)):
    s = ReservationSegment(reservation_id=r.id, vehicle_id=vehicule.id, start_at=debut, end_at=fin)
    db.session.add(s)
    db.session.commit()
    return s


# --- un refus libère le véhicule ------------------------------------------------

@pytest.mark.parametrize("statut", ["rejected", "cancelled"])
def test_refused_or_cancelled_segment_frees_the_vehicle(parc, statut):
    """Reproduit par l'audit : le véhicule restait bloqué."""
    r = _reservation(parc, statut="pending")
    _segment(r, parc["v1"])
    r.status = statut
    db.session.commit()
    assert not has_conflict(parc["v1"].id, datetime(2026, 10, 5, 9), datetime(2026, 10, 5, 10))


def test_segment_of_a_live_reservation_still_blocks(parc):
    """Non-régression : une réservation en cours bloque toujours."""
    r = _reservation(parc)
    _segment(r, parc["v1"])
    assert has_conflict(parc["v1"].id, datetime(2026, 10, 5, 9), datetime(2026, 10, 5, 10))


def test_refused_segment_is_kept_for_history(parc):
    """On ne supprime rien : le segment ne bloque plus, il reste consultable."""
    r = _reservation(parc, statut="pending")
    _segment(r, parc["v1"])
    r.status = "rejected"
    db.session.commit()
    assert ReservationSegment.query.count() == 1


# --- période d'un segment -----------------------------------------------------------

@pytest.mark.parametrize("debut,fin,motif", [
    (datetime(2026, 10, 5, 17), datetime(2026, 10, 5, 8), "après le début"),
    (datetime(2026, 10, 5, 10), datetime(2026, 10, 5, 10), "après le début"),
    (datetime(2026, 10, 4, 8), datetime(2026, 10, 5, 12), "dans celle de la réservation"),
    (datetime(2026, 10, 6, 8), datetime(2026, 10, 7, 12), "dans celle de la réservation"),
    (None, datetime(2026, 10, 5, 12), "Indiquez"),
])
def test_invalid_period_is_explained(parc, debut, fin, motif):
    r = _reservation(parc)
    assert motif in segment_period_error(r, debut, fin)


def test_valid_period_is_accepted(parc):
    r = _reservation(parc)
    assert segment_period_error(r, datetime(2026, 10, 5, 8), datetime(2026, 10, 5, 12)) is None


def test_inverted_segment_is_refused_before_writing(parc):
    """Reproduit par l'audit : il était enregistré tel quel."""
    r = _reservation(parc, vehicule=parc["v2"])
    reponse = _client(parc["chef"]).post(f"/admin/manage/{r.id}", data={
        "action": "segment", "vehicle_id": str(parc["v1"].id),
        "start_at": "2026-10-05T17:00", "end_at": "2026-10-05T08:00"},
        follow_redirects=True)
    assert ReservationSegment.query.count() == 0
    assert "après le début" in reponse.data.decode()


def test_segment_outside_the_reservation_is_refused(parc):
    r = _reservation(parc, vehicule=parc["v2"])
    _client(parc["chef"]).post(f"/admin/manage/{r.id}", data={
        "action": "segment", "vehicle_id": str(parc["v1"].id),
        "start_at": "2026-11-09T08:00", "end_at": "2026-11-09T17:00"})
    assert ReservationSegment.query.count() == 0


@pytest.mark.parametrize("vehicule", ["", "abc", "9999"])
def test_missing_or_unknown_vehicle_is_refused_without_error(parc, vehicule):
    """Un champ absent levait une erreur 500 ; un identifiant inexistant
    produisait un segment pointant dans le vide."""
    r = _reservation(parc, vehicule=parc["v2"])
    reponse = _client(parc["chef"]).post(f"/admin/manage/{r.id}", data={
        "action": "segment", "vehicle_id": vehicule,
        "start_at": "2026-10-05T08:00", "end_at": "2026-10-05T12:00"})
    assert reponse.status_code == 302
    assert ReservationSegment.query.count() == 0


# --- jour dans l'adresse ------------------------------------------------------------

def test_day_outside_the_reservation_makes_no_inverted_segment(parc):
    """Trouvé en corrigeant : un jour hors de la réservation donnait un début
    après la fin — la vraie source des segments inversés."""
    r = _reservation(parc, vehicule=parc["v2"])
    reponse = _client(parc["chef"]).post(f"/admin/manage/{r.id}?day=2026-12-25", data={
        "action": "segment_day", "vehicle_id": str(parc["v1"].id)})
    assert reponse.status_code == 302
    assert ReservationSegment.query.count() == 0


def test_malformed_day_does_not_crash(parc):
    r = _reservation(parc, vehicule=parc["v2"])
    reponse = _client(parc["chef"]).get(f"/admin/manage/{r.id}?day=pas-une-date")
    assert reponse.status_code == 302


def test_day_inside_the_reservation_still_works(parc):
    """Non-régression : réattribuer une journée depuis le planning."""
    r = _reservation(parc, vehicule=parc["v2"])
    _client(parc["chef"]).post(f"/admin/manage/{r.id}?day=2026-10-05", data={
        "action": "segment_day", "vehicle_id": str(parc["v1"].id)})
    sur_v1 = ReservationSegment.query.filter_by(vehicle_id=parc["v1"].id).all()
    assert len(sur_v1) == 1
    assert sur_v1[0].start_at.date() == LUNDI.date()


# --- doubles réservations -------------------------------------------------------------

@pytest.fixture
def course_perdue(monkeypatch):
    """Simuler un autre administrateur qui attribue le véhicule entre la
    vérification et l'enregistrement."""
    appels = {"n": 0}
    vrai = app_module.has_conflict

    def second_appel_occupe(*args, **kwargs):
        appels["n"] += 1
        return appels["n"] > 1 or vrai(*args, **kwargs)

    monkeypatch.setattr(app_module, "has_conflict", second_appel_occupe)
    return appels


def test_segment_day_is_rechecked_before_saving(parc, course_perdue):
    r = _reservation(parc, vehicule=parc["v2"])
    _client(parc["chef"]).post(f"/admin/manage/{r.id}?day=2026-10-05", data={
        "action": "segment_day", "vehicle_id": str(parc["v1"].id)})
    assert course_perdue["n"] == 2, "la seconde vérification doit avoir lieu"
    assert ReservationSegment.query.filter_by(vehicle_id=parc["v1"].id).count() == 0


def test_segment_edit_is_rechecked_before_saving(parc, course_perdue):
    r = _reservation(parc)
    seg = _segment(r, parc["v2"])
    _client(parc["chef"]).post(f"/admin/manage/segment/{seg.id}", data={
        "action": "update", "vehicle_id": str(parc["v1"].id)})
    assert course_perdue["n"] == 2
    db.session.expire_all()
    assert db.session.get(ReservationSegment, seg.id).vehicle_id == parc["v2"].id


# --- clés étrangères ------------------------------------------------------------------

def test_foreign_keys_are_enforced(ctx):
    assert db.session.execute(db.text("PRAGMA foreign_keys")).scalar() == 1


def test_a_segment_can_no_longer_outlive_its_reservation(parc):
    """Les fantômes réparés en octobre ne peuvent plus se reformer."""
    r = _reservation(parc)
    _segment(r, parc["v1"])
    with pytest.raises(Exception):
        Reservation.query.filter_by(id=r.id).delete(synchronize_session=False)
        db.session.commit()
    db.session.rollback()


def test_deleting_a_user_clears_every_reference_to_him(parc):
    """Sans clés étrangères la suppression laissait des références pendantes ;
    avec elles, elle aurait échoué sur les deux tables oubliées."""
    jean, chef = parc["jean"], parc["chef"]
    un = VehicleUnavailability(vehicle_id=parc["v1"].id, start_at=LUNDI, category="autre",
                               created_by=jean.id)
    db.session.add(un)
    db.session.add(CredentialHandoff(token="t", user_id=jean.id, password="x",
                                     regenerated=False, mail_sent=True))
    db.session.commit()

    reponse = _client(chef).post(f"/admin/delete/{jean.id}")
    assert reponse.status_code == 302
    db.session.expire_all()
    assert db.session.get(User, jean.id) is None
    assert db.session.get(VehicleUnavailability, un.id).created_by is None, \
        "l'indisponibilité reste, sans auteur"
    assert CredentialHandoff.query.count() == 0


def test_foreign_keys_can_be_switched_off_without_code(ctx, monkeypatch):
    """Soupape pour la production : SQLITE_FOREIGN_KEYS=false dans le .env."""
    monkeypatch.setitem(app.config, "SQLITE_FOREIGN_KEYS", False)
    moteur = db.engine
    moteur.dispose()
    with moteur.connect() as connexion:
        assert connexion.exec_driver_sql("PRAGMA foreign_keys").scalar() == 0
    monkeypatch.setitem(app.config, "SQLITE_FOREIGN_KEYS", True)
    moteur.dispose()


# --- adresses abîmées -------------------------------------------------------------------

@pytest.mark.parametrize("requete", [
    "y=2026&m=13", "y=2026&m=0", "y=abc&m=3", "y=2026&m=", "y=99999&m=1",
])
def test_broken_month_address_shows_the_current_month(parc, requete):
    """Reproduit par l'audit : « m=13 » levait une erreur 500."""
    reponse = _client(parc["jean"]).get(f"/calendar/month?{requete}")
    assert reponse.status_code == 200
