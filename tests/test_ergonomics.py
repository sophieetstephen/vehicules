"""Ergonomie : ce que l'audit a observé en production, sur téléphone surtout.

* le planning mobile répétait chaque indisponibilité permanente jour après
  jour, jusqu'à la fin du mois ;
* aucun moyen d'arriver directement au jour actuel ;
* sur l'accueil administrateur, les demandes à traiter arrivaient après tout
  le reste ;
* des liens « Réserver » par véhicule laissaient croire qu'on choisissait son
  véhicule ;
* sur la fiche d'une réservation, son propre véhicule apparaissait « Occupé ».
"""

import importlib
from datetime import datetime

import pytest

from app import app
from models import db, User, Vehicle, Reservation, VehicleUnavailability

app_module = importlib.import_module("app")

NOW = datetime(2026, 9, 18, 10, 0)


@pytest.fixture
def ctx(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    monkeypatch.setattr(app_module, "local_now", lambda: NOW)
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    monkeypatch.setattr(app_module, "check_mail_login", lambda *a, **k: (True, "login ok"))
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
    vs = [Vehicle(code=c, label=f"Véhicule {c}") for c in ("VL1", "VL2", "VRID")]
    db.session.add_all(vs)
    db.session.commit()
    return {"vl1": vs[0], "vl2": vs[1], "vrid": vs[2],
            "jean": _user(), "chef": _user("Chef", User.ROLE_SUPERADMIN)}


def _reservation(parc, debut, fin, vehicule=None, statut="approved", motif="Stage"):
    r = Reservation(user_id=parc["jean"].id, vehicle_id=vehicule.id if vehicule else None,
                    start_at=debut, end_at=fin, status=statut, purpose=motif)
    db.session.add(r)
    db.session.commit()
    return r


def _liste_mobile(html):
    return html.split('class="calendar-mobile"')[1]


# --- planning sur téléphone ----------------------------------------------------

def test_long_unavailability_is_listed_once(parc):
    """Constat de l'audit : trois pannes « jusqu'à nouvel ordre » depuis le 19
    remplissaient chaque jour jusqu'au 30."""
    for v in (parc["vl1"], parc["vl2"], parc["vrid"]):
        db.session.add(VehicleUnavailability(vehicle_id=v.id, start_at=datetime(2026, 9, 19),
                                             end_at=None, category="mecanique", details=v.code))
    db.session.commit()
    liste = _liste_mobile(_client(parc["jean"]).get("/calendar/month?y=2026&m=9").data.decode())
    assert liste.count("Véhicules indisponibles") == 1
    assert liste.count("Indispo.") == 3, "une ligne par indisponibilité, pas par jour"
    assert "mobile-day-card mobile-day-today" not in liste
    assert 'id="jour-2026-09-2' not in liste, "plus de journées faites d'indisponibilités"


def test_days_still_list_their_reservations(parc):
    """Non-régression : une réservation garde sa journée."""
    _reservation(parc, datetime(2026, 9, 22, 8), datetime(2026, 9, 22, 12), parc["vl1"])
    liste = _liste_mobile(_client(parc["jean"]).get("/calendar/month?y=2026&m=9").data.decode())
    assert 'id="jour-2026-09-22"' in liste
    assert "Stage" in liste


def test_jump_to_today_leads_to_the_next_busy_day(parc):
    """Arriver directement au jour actuel, sans perdre l'accès aux jours passés."""
    _reservation(parc, datetime(2026, 9, 10, 8), datetime(2026, 9, 10, 12), parc["vl1"])
    _reservation(parc, datetime(2026, 9, 22, 8), datetime(2026, 9, 22, 12), parc["vl2"])
    liste = _liste_mobile(_client(parc["jean"]).get("/calendar/month?y=2026&m=9").data.decode())
    assert 'href="#jour-2026-09-22"' in liste
    assert 'id="jour-2026-09-10"' in liste, "les jours passés restent là"


def test_no_jump_link_for_another_month(parc):
    _reservation(parc, datetime(2026, 11, 10, 8), datetime(2026, 11, 10, 12), parc["vl1"])
    liste = _liste_mobile(_client(parc["jean"]).get("/calendar/month?y=2026&m=11").data.decode())
    assert "Aller à aujourd'hui" not in liste


# --- accueil administrateur --------------------------------------------------------

def test_pending_requests_come_first(parc):
    _reservation(parc, datetime(2026, 9, 25, 8), datetime(2026, 9, 25, 12), statut="pending")
    html = _client(parc["chef"]).get("/").data.decode()
    assert 'class="pending-count">1<' in html
    assert "demande à traiter" in html
    assert html.index("pending-banner") < html.index("quick-actions")
    assert '<a class="pending-banner" href="/admin/reservations">' in html


def test_no_banner_when_nothing_is_pending(parc):
    html = _client(parc["chef"]).get("/").data.decode()
    assert "pending-banner" not in html


def test_ordinary_user_never_sees_the_banner(parc):
    _reservation(parc, datetime(2026, 9, 25, 8), datetime(2026, 9, 25, 12), statut="pending")
    html = _client(parc["jean"]).get("/").data.decode()
    assert "pending-banner" not in html


# --- demande et attribution ----------------------------------------------------------

def test_no_per_vehicle_booking_link(parc):
    """Le lien laissait croire qu'on réservait ce véhicule-là."""
    html = _client(parc["jean"]).get("/").data.decode()
    tableau = html.split('class="today-section"')[1].split("Mes réservations")[0]
    assert "/request/new" not in tableau


def test_form_says_the_vehicle_is_assigned_later(parc):
    html = _client(parc["jean"]).get("/request/new").data.decode()
    assert "Un administrateur choisit" in html


# --- fiche d'une réservation -----------------------------------------------------------

def test_own_vehicle_is_not_shown_as_busy(parc):
    """Constat de l'audit : le véhicule attribué apparaissait « Occupé »,
    coché mais désactivé — donc jamais envoyé par le formulaire."""
    r = _reservation(parc, datetime(2026, 9, 25, 8), datetime(2026, 9, 25, 12), parc["vl1"])
    html = _client(parc["chef"]).get(f"/admin/manage/{r.id}").data.decode()
    option = html.split(f'value="{parc["vl1"].id}"')[1].split("</label>")[0]
    assert "Attribué à cette réservation" in option
    entree = html.split(f'value="{parc["vl1"].id}"')[1].split(">")[0]
    assert "disabled" not in entree


def test_vehicle_taken_by_someone_else_is_still_busy(parc):
    """Non-régression : l'exclusion ne vaut que pour la réservation gérée."""
    _reservation(parc, datetime(2026, 9, 25, 8), datetime(2026, 9, 25, 12), parc["vl2"])
    r = _reservation(parc, datetime(2026, 9, 25, 8), datetime(2026, 9, 25, 12), parc["vl1"])
    html = _client(parc["chef"]).get(f"/admin/manage/{r.id}").data.decode()
    option = html.split(f'value="{parc["vl2"].id}"')[1].split("</label>")[0]
    assert "Occupé" in option
