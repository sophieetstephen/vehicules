"""Vue semaine du planning, et allègement de la vue mois.

Sur ordinateur, le mois entier occupait trente et une colonnes de 40 pixels :
le texte des badges était illisible et la fin du mois sortait de l'écran. La
vue semaine offre sept colonnes larges ; la vue mois ne garde qu'une pastille
par occupation, le détail s'ouvrant au clic.
"""

import importlib
import os
import pathlib
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, calendar_grid
from models import db, User, Vehicle, Reservation, ReservationSegment, VehicleUnavailability

app_module = importlib.import_module("app")

# Un vendredi, pour vérifier que la semaine démarre bien le lundi précédent.
NOW = datetime(2026, 9, 18, 10, 0)


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
    v1, v2 = Vehicle(code="VL1", label="Léger 1"), Vehicle(code="VL2", label="Léger 2")
    db.session.add_all([v1, v2])
    db.session.commit()
    return v1, v2


def _reservation(user, vehicle, start, end, purpose="Formation"):
    r = Reservation(user_id=user.id, vehicle_id=vehicle.id, start_at=start, end_at=end,
                    status="approved", purpose=purpose)
    db.session.add(r)
    db.session.commit()
    return r


def _client_as(user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = user.id
        s["pwd_stamp"] = user.session_stamp(app.config["SECRET_KEY"])
    return c


# --- la semaine affichée -----------------------------------------------------

def test_week_starts_on_monday(ctx):
    """Sans paramètre, c'est la semaine en cours, du lundi au dimanche."""
    jean = _user("Jean", "Dupont", "j@ex.fr")
    _vehicles()
    html = _client_as(jean).get("/calendar/week").data.decode()
    # NOW est le vendredi 18 septembre 2026 : lundi 14 → dimanche 20.
    assert "14/09 – 20/09" in html
    entete = html.split("<thead>")[1].split("</thead>")[0]
    assert entete.count("calendar-day-header") == 7
    for jour in ("lun", "mar", "mer", "jeu", "ven", "sam", "dim"):
        assert jour in entete


def test_week_follows_the_requested_day(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    _vehicles()
    html = _client_as(jean).get("/calendar/week?d=2026-10-07").data.decode()
    assert "05/10 – 11/10" in html


def test_unreadable_day_falls_back_to_this_week(ctx):
    """Une adresse tapée ou tronquée ne doit pas renvoyer une erreur."""
    jean = _user("Jean", "Dupont", "j@ex.fr")
    _vehicles()
    reponse = _client_as(jean).get("/calendar/week?d=n-importe-quoi")
    assert reponse.status_code == 200
    assert "14/09 – 20/09" in reponse.data.decode()


def test_previous_and_next_week(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    _vehicles()
    html = _client_as(jean).get("/calendar/week?d=2026-09-16").data.decode()
    assert "/calendar/week?d=2026-09-07" in html
    assert "/calendar/week?d=2026-09-21" in html


# --- passer d'une vue à l'autre ---------------------------------------------

def test_each_view_offers_the_other(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    _vehicles()
    c = _client_as(jean)

    mois = c.get("/calendar/month?y=2026&m=9").data.decode()
    assert "/calendar/week?d=2026-09-01" in mois
    assert "Aujourd'hui" in mois

    semaine = c.get("/calendar/week?d=2026-09-16").data.decode()
    assert "y=2026&amp;m=9" in semaine


# --- contenu des cases -------------------------------------------------------

def test_week_cell_shows_name_slot_and_purpose(ctx):
    """Sept colonnes larges : plus besoin de survoler pour lire."""
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    _reservation(jean, v1, datetime(2026, 9, 16, 8), datetime(2026, 9, 16, 12), "Manœuvre")
    html = _client_as(jean).get("/calendar/week?d=2026-09-16").data.decode()
    carte = html.split('class="cal-card')[1].split("</button>")[0]
    assert "Dupont Jean" in carte
    assert "Matin" in carte
    assert "Manœuvre" in carte


def test_month_cell_is_reduced_to_one_letter(ctx):
    """Une case de trente pixels ne peut pas contenir un nom."""
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    _reservation(jean, v1, datetime(2026, 9, 16, 8), datetime(2026, 9, 16, 12))
    _reservation(jean, v1, datetime(2026, 9, 17, 13), datetime(2026, 9, 17, 17))
    _reservation(jean, v1, datetime(2026, 9, 18, 8), datetime(2026, 9, 18, 17))
    html = _client_as(jean).get("/calendar/month?y=2026&m=9").data.decode()
    # La légende emploie les mêmes pastilles : on ne regarde que le tableau.
    corps = html.split("<tbody>")[1].split("</tbody>")[0]
    lettres = [bloc.split("</button>")[0].rsplit(">", 1)[1]
               for bloc in corps.split("data-calendar-item")[1:]]
    assert lettres == ["M", "A", "J"], "matin, après-midi, journée"
    assert "Dupont Jean" not in corps.split("title=")[0]


def test_details_are_available_on_click(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    _reservation(jean, v1, datetime(2026, 9, 16, 8), datetime(2026, 9, 16, 12), "Manœuvre")
    html = _client_as(jean).get("/calendar/month?y=2026&m=9").data.decode()
    pastille = html.split("data-calendar-item")[1].split(">")[0]
    assert 'data-name="Dupont Jean"' in pastille
    assert 'data-slot="Matin"' in pastille
    assert 'data-purpose="Manœuvre"' in pastille
    assert 'data-day="mer 16/09/2026"' in pastille
    assert 'data-vehicle="VL1 – Léger 1"' in pastille
    assert 'id="calendarDetail"' in html


def test_plain_user_gets_no_management_link(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    _reservation(jean, v1, datetime(2026, 9, 16, 8), datetime(2026, 9, 16, 12))
    html = _client_as(jean).get("/calendar/month?y=2026&m=9").data.decode()
    assert "data-url" not in html


def test_admin_keeps_the_management_link(ctx):
    admin = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_ADMIN)
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    r = _reservation(jean, v1, datetime(2026, 9, 16, 8), datetime(2026, 9, 16, 12))
    html = _client_as(admin).get("/calendar/month?y=2026&m=9").data.decode()
    assert f'data-url="/admin/manage/{r.id}?day=2026-09-16"' in html


# --- la grille calculée côté Python ------------------------------------------

def test_segment_day_belongs_to_the_segment_only(ctx):
    """Le jour repris par un segment ne doit pas rester sur le véhicule d'origine."""
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, v2 = _vehicles()
    r = _reservation(jean, v1, datetime(2026, 9, 16, 8), datetime(2026, 9, 18, 17))
    seg = ReservationSegment(reservation_id=r.id, vehicle_id=v2.id,
                             start_at=datetime(2026, 9, 17, 8), end_at=datetime(2026, 9, 17, 17))
    db.session.add(seg)
    db.session.commit()

    with app.test_request_context("/calendar/week"):
        grille = calendar_grid([v1, v2], [r], [seg], [], datetime(2026, 9, 14), datetime(2026, 9, 21), jean)

    assert grille["cells"][v1.id]["2026-09-17"] == []
    assert len(grille["cells"][v2.id]["2026-09-17"]) == 1
    assert len(grille["cells"][v1.id]["2026-09-16"]) == 1
    assert len(grille["cells"][v1.id]["2026-09-18"]) == 1


def test_overlapping_unavailabilities_show_one_chip(ctx):
    """Deux pannes déclarées sur les mêmes jours ne doivent pas empiler
    deux pastilles dans une case de trente pixels."""
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    a = VehicleUnavailability(vehicle_id=v1.id, start_at=datetime(2026, 9, 14),
                              end_at=datetime(2026, 9, 18), category="mecanique")
    b = VehicleUnavailability(vehicle_id=v1.id, start_at=datetime(2026, 9, 15),
                              end_at=datetime(2026, 9, 17), category="entretien")
    db.session.add_all([a, b])
    db.session.commit()

    with app.test_request_context("/calendar/week"):
        grille = calendar_grid([v1], [], [], [a, b], datetime(2026, 9, 14), datetime(2026, 9, 21), jean)

    assert len(grille["cells"][v1.id]["2026-09-16"]) == 1
    assert grille["cells"][v1.id]["2026-09-16"][0]["letter"] == "I"


def test_open_ended_unavailability_covers_the_whole_window(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    un = VehicleUnavailability(vehicle_id=v1.id, start_at=datetime(2026, 9, 16),
                               end_at=None, category="mecanique", details="moteur")
    db.session.add(un)
    db.session.commit()

    with app.test_request_context("/calendar/week"):
        grille = calendar_grid([v1], [], [], [un], datetime(2026, 9, 14), datetime(2026, 9, 21), jean)

    assert grille["cells"][v1.id]["2026-09-15"] == []
    for jour in ("2026-09-16", "2026-09-20"):
        assert grille["cells"][v1.id][jour][0]["period"].endswith("jusqu'à nouvel ordre")


def test_today_is_highlighted(ctx):
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    with app.test_request_context("/calendar/week"):
        grille = calendar_grid([v1], [], [], [], datetime(2026, 9, 14), datetime(2026, 9, 21), jean)
    marques = [j["key"] for j in grille["days"] if j["today"]]
    assert marques == ["2026-09-18"]
    weekend = [j["key"] for j in grille["days"] if j["weekend"]]
    assert weekend == ["2026-09-19", "2026-09-20"]


# --- mise en page -------------------------------------------------------------

def test_columns_have_a_fixed_equal_width():
    """Sans cela le navigateur élargit les colonnes chargées et pousse la fin
    du mois hors de l'écran."""
    css = pathlib.Path("static/custom.css").read_text(encoding="utf-8")
    bloc = css.split(".calendar-table {")[1].split("}")[0]
    assert "table-layout: fixed" in bloc
    assert "width: 100%" in bloc


def test_day_header_stays_visible_when_scrolling():
    css = pathlib.Path("static/custom.css").read_text(encoding="utf-8")
    bloc = css.split(".calendar-table thead th {")[1].split("}")[0]
    assert "position: sticky" in bloc


def test_weekend_shading_survives_bootstrap():
    """Bootstrap peint ses cellules avec une ombre interne : un simple
    ``background`` était recouvert et le week-end restait blanc."""
    css = pathlib.Path("static/custom.css").read_text(encoding="utf-8")
    bloc = css.split(".calendar-table .cal-weekend {")[1].split("}")[0]
    assert "inset 0 0 0 9999px" in bloc


def test_unavailability_card_stays_compact(ctx):
    """Le motif d'une panne tient rarement sur une ligne : la case annonce
    l'indisponibilité, le détail complet attend le clic."""
    jean = _user("Jean", "Dupont", "j@ex.fr")
    v1, _ = _vehicles()
    db.session.add(VehicleUnavailability(vehicle_id=v1.id, start_at=datetime(2026, 9, 14),
                                         end_at=datetime(2026, 9, 30), category="mecanique",
                                         details="boîte de vitesses"))
    db.session.commit()
    html = _client_as(jean).get("/calendar/week?d=2026-09-16").data.decode()
    carte = html.split('class="cal-card cal-card-unav"')[1].split("</button>")[0]
    assert "Indisponible" in carte
    assert "boîte de vitesses" in carte
    # La période encombrerait la case ; elle reste dans la fenêtre de détail.
    assert "du 14/09/2026 au 30/09/2026" in carte.split(">", 1)[0]
    assert "du 14/09/2026 au 30/09/2026" not in carte.split(">", 1)[1]


def test_detail_window_is_built_on_click():
    """Bootstrap est chargé en fin de page : construire la fenêtre au
    chargement du script la laissait muette."""
    script = pathlib.Path("templates/_calendar_detail.html").read_text(encoding="utf-8")
    assert script.index("addEventListener") < script.index("new bootstrap.Modal")
