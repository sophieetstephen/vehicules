"""Véhicules à usage réservé et prêts temporaires.

VL1 (chef de centre) et VL2 (adjoint) étaient déclarés « indisponibles jusqu'à
nouvel ordre », comme une panne. Règles convenues :

* hors prêt, un véhicule à usage réservé n'est attribuable à aucune demande ;
* pendant un prêt, à n'importe quelle demande, comme un véhicule du parc ;
* une panne l'emporte toujours ;
* n'importe quel administrateur enregistre un prêt, l'accord du titulaire
  étant demandé de vive voix ; on garde la trace de qui l'a enregistré.
"""

import importlib
from datetime import datetime, date

import pytest

from app import (app, has_conflict, loans_cover, reserved_block_reason,
                 calendar_grid, calendar_entries, today_overview)
from models import (db, User, Vehicle, Reservation, ReservationSegment,
                    VehicleUnavailability, VehicleLoan)

app_module = importlib.import_module("app")

NOW = datetime(2026, 10, 7, 10, 0)          # un mercredi
MATIN = (datetime(2026, 10, 7, 8), datetime(2026, 10, 7, 12))


@pytest.fixture
def ctx(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    monkeypatch.setattr(app_module, "local_now", lambda: NOW)
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    monkeypatch.setattr(app_module, "check_mail_login", lambda *a, **k: (True, "ok"))
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
    vl1 = Vehicle(code="VL1", label="Chef de Centre", reserved_for="Chef de centre")
    vl2 = Vehicle(code="VL2", label="Adjoint", reserved_for="Adjoint")
    vid2 = Vehicle(code="VID2", label="Véhicule 5 places")
    db.session.add_all([vl1, vl2, vid2])
    db.session.commit()
    return {"vl1": vl1, "vl2": vl2, "vid2": vid2, "jean": _user(),
            "adjoint": _user("Adjoint", User.ROLE_ADMIN),
            "chef": _user("Chef", User.ROLE_SUPERADMIN)}


def _pret(vehicule, du, au, auteur=None, motif=None):
    p = VehicleLoan(vehicle_id=vehicule.id,
                    start_at=datetime.combine(du, datetime.min.time()),
                    end_at=datetime.combine(au, datetime.max.time()),
                    reason=motif, created_by=auteur.id if auteur else None)
    db.session.add(p)
    db.session.commit()
    return p


def _demande(parc, debut, fin, vehicule=None, statut="pending"):
    r = Reservation(user_id=parc["jean"].id, vehicle_id=vehicule.id if vehicule else None,
                    start_at=debut, end_at=fin, status=statut, purpose="Formation")
    db.session.add(r)
    db.session.commit()
    return r


# --- la règle -------------------------------------------------------------------

def test_reserved_vehicle_is_not_assignable_without_a_loan(parc):
    assert has_conflict(parc["vl1"].id, *MATIN)
    assert reserved_block_reason(parc["vl1"], *MATIN) == "Usage réservé — Chef de centre"


def test_ordinary_vehicle_is_unaffected(parc):
    assert not has_conflict(parc["vid2"].id, *MATIN)
    assert reserved_block_reason(parc["vid2"], *MATIN) is None


def test_loan_makes_it_assignable(parc):
    _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9))
    assert not has_conflict(parc["vl1"].id, *MATIN)


def test_loan_must_cover_the_whole_period(parc):
    """Un prêt jusqu'au mercredi ne suffit pas pour une demande jusqu'au vendredi."""
    _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 7))
    assert has_conflict(parc["vl1"].id, datetime(2026, 10, 7, 8), datetime(2026, 10, 9, 17))


def test_consecutive_loans_join_up(parc):
    """Deux prêts qui se suivent se touchent à la microseconde près."""
    _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 7))
    _pret(parc["vl1"], date(2026, 10, 8), date(2026, 10, 9))
    assert not has_conflict(parc["vl1"].id, datetime(2026, 10, 7, 8), datetime(2026, 10, 9, 17))


def test_a_gap_between_loans_blocks(parc):
    _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 6))
    _pret(parc["vl1"], date(2026, 10, 8), date(2026, 10, 9))
    assert has_conflict(parc["vl1"].id, datetime(2026, 10, 6, 8), datetime(2026, 10, 8, 17))


def test_a_breakdown_beats_a_loan(parc):
    """Un prêt ne lève jamais une panne."""
    _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9))
    db.session.add(VehicleUnavailability(vehicle_id=parc["vl1"].id,
                                         start_at=datetime(2026, 10, 7), end_at=None,
                                         category="mecanique"))
    db.session.commit()
    assert has_conflict(parc["vl1"].id, *MATIN)


def test_loans_cover_helper_edges():
    class P:
        def __init__(self, a, b):
            self.start_at, self.end_at = a, b
    d = datetime
    assert loans_cover([], d(2026, 1, 1), d(2026, 1, 2)) is False
    assert loans_cover([P(d(2026, 1, 1), d(2026, 1, 3))], d(2026, 1, 1, 8), d(2026, 1, 2)) is True
    assert loans_cover([P(d(2026, 1, 2), d(2026, 1, 3))], d(2026, 1, 1), d(2026, 1, 2, 12)) is False


# --- l'attribution --------------------------------------------------------------------

def test_approving_with_a_reserved_vehicle_is_refused_and_explained(parc):
    r = _demande(parc, *MATIN)
    reponse = _client(parc["adjoint"]).post(f"/admin/manage/{r.id}", data={
        "action": "approve", "vehicle_id": str(parc["vl1"].id)}, follow_redirects=True)
    db.session.expire_all()
    assert db.session.get(Reservation, r.id).status == "pending"
    assert "hors période de prêt" in reponse.data.decode()


def test_approving_during_a_loan_works(parc):
    _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9))
    r = _demande(parc, *MATIN)
    _client(parc["adjoint"]).post(f"/admin/manage/{r.id}", data={
        "action": "approve", "vehicle_id": str(parc["vl1"].id)})
    db.session.expire_all()
    r = db.session.get(Reservation, r.id)
    assert r.status == "approved" and r.vehicle_id == parc["vl1"].id


def test_approve_without_vehicle_does_not_crash(parc):
    """Oubli du correctif précédent : cette branche levait encore une 500."""
    r = _demande(parc, *MATIN)
    reponse = _client(parc["adjoint"]).post(f"/admin/manage/{r.id}", data={"action": "approve"})
    assert reponse.status_code == 302


def test_manage_page_says_why(parc):
    r = _demande(parc, *MATIN)
    html = _client(parc["adjoint"]).get(f"/admin/manage/{r.id}").data.decode()
    option = html.split(f'value="{parc["vl1"].id}"')[1].split("</label>")[0]
    assert "Usage réservé — Chef de centre" in option
    assert "disabled" in html.split(f'value="{parc["vl1"].id}"')[1].split(">")[0]


# --- la gestion des prêts ------------------------------------------------------------------

@pytest.mark.parametrize("role", ["adjoint", "chef"])
def test_any_administrator_records_a_loan(parc, role):
    _client(parc[role]).post(f"/admin/vehicles/{parc['vl1'].id}/loans", data={
        "start_date": "2026-10-12", "end_date": "2026-10-16", "reason": "congés du chef"})
    pret = VehicleLoan.query.one()
    assert pret.created_by == parc[role].id
    assert pret.reason == "congés du chef"
    assert pret.end_at.date() == date(2026, 10, 16), "la date de fin est incluse"


def test_a_plain_user_cannot_lend(parc):
    reponse = _client(parc["jean"]).post(f"/admin/vehicles/{parc['vl1'].id}/loans", data={
        "start_date": "2026-10-12", "end_date": "2026-10-16"})
    assert reponse.status_code in (302, 403)
    assert VehicleLoan.query.count() == 0


def test_end_before_start_is_refused(parc):
    _client(parc["adjoint"]).post(f"/admin/vehicles/{parc['vl1'].id}/loans", data={
        "start_date": "2026-10-16", "end_date": "2026-10-12"})
    assert VehicleLoan.query.count() == 0


def test_ordinary_vehicle_has_no_loan_page(parc):
    reponse = _client(parc["adjoint"]).get(f"/admin/vehicles/{parc['vid2'].id}/loans")
    assert reponse.status_code == 302


def test_loan_over_a_breakdown_warns(parc):
    db.session.add(VehicleUnavailability(vehicle_id=parc["vl1"].id,
                                         start_at=datetime(2026, 10, 13), end_at=None,
                                         category="mecanique"))
    db.session.commit()
    reponse = _client(parc["adjoint"]).post(f"/admin/vehicles/{parc['vl1'].id}/loans", data={
        "start_date": "2026-10-12", "end_date": "2026-10-16"}, follow_redirects=True)
    assert "ne sera pas attribuable ces jours-là" in reponse.data.decode()


def test_removing_a_loan_in_use_is_refused(parc):
    """Retirer le prêt laisserait la réservation sur un véhicule que plus rien
    n'autorise."""
    pret = _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9))
    _demande(parc, *MATIN, vehicule=parc["vl1"], statut="approved")
    reponse = _client(parc["adjoint"]).post(f"/admin/vehicles/loans/{pret.id}/delete",
                                            follow_redirects=True)
    assert VehicleLoan.query.count() == 1
    assert "Réattribuez-les" in reponse.data.decode()


def test_removing_a_loan_is_refused_for_a_segment_too(parc):
    pret = _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9))
    r = _demande(parc, datetime(2026, 10, 7, 8), datetime(2026, 10, 8, 17),
                 vehicule=parc["vid2"], statut="approved")
    db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=parc["vl1"].id,
                                      start_at=datetime(2026, 10, 8, 8),
                                      end_at=datetime(2026, 10, 8, 17)))
    db.session.commit()
    _client(parc["adjoint"]).post(f"/admin/vehicles/loans/{pret.id}/delete")
    assert VehicleLoan.query.count() == 1


def test_removing_a_loan_covered_by_another_is_allowed(parc):
    pret = _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9))
    _pret(parc["vl1"], date(2026, 10, 6), date(2026, 10, 8))
    _demande(parc, *MATIN, vehicule=parc["vl1"], statut="approved")
    _client(parc["adjoint"]).post(f"/admin/vehicles/loans/{pret.id}/delete")
    assert VehicleLoan.query.count() == 1


def test_refused_reservation_does_not_hold_a_loan(parc):
    pret = _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9))
    _demande(parc, *MATIN, vehicule=parc["vl1"], statut="rejected")
    _client(parc["adjoint"]).post(f"/admin/vehicles/loans/{pret.id}/delete")
    assert VehicleLoan.query.count() == 0


def test_vehicle_form_sets_and_clears_the_holder(parc):
    admin = _client(parc["adjoint"])
    admin.post(f"/admin/vehicles/{parc['vid2'].id}/edit", data={
        "code": "VID2", "label": "Véhicule 5 places", "category": "", "reserved_for": "Médecin"})
    db.session.expire_all()
    assert db.session.get(Vehicle, parc["vid2"].id).reserved_for == "Médecin"
    admin.post(f"/admin/vehicles/{parc['vid2'].id}/edit", data={
        "code": "VID2", "label": "Véhicule 5 places", "category": "", "reserved_for": "  "})
    db.session.expire_all()
    assert db.session.get(Vehicle, parc["vid2"].id).reserved_for is None


def test_deleting_the_lender_keeps_the_loan(parc):
    """Même traitement que les indisponibilités : le prêt reste, sans auteur."""
    auteur = _user("Temporaire", User.ROLE_ADMIN)
    pret = _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9), auteur=auteur)
    _client(parc["chef"]).post(f"/admin/delete/{auteur.id}")
    db.session.expire_all()
    assert db.session.get(VehicleLoan, pret.id).created_by is None


# --- l'affichage ------------------------------------------------------------------------------

def _grille(parc, prets=()):
    with app.test_request_context("/"):
        return calendar_grid([parc["vl1"], parc["vid2"]], [], [], [],
                             datetime(2026, 10, 5), datetime(2026, 10, 12), None, list(prets))


def test_grid_marks_days_outside_loans(parc):
    pret = _pret(parc["vl1"], date(2026, 10, 7), date(2026, 10, 8))
    grille = _grille(parc, [pret])
    lettres = {j: [i["letter"] for i in grille["cells"][parc["vl1"].id][j]]
               for j in ("2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09")}
    assert lettres == {"2026-10-06": ["R"], "2026-10-07": [], "2026-10-08": [], "2026-10-09": ["R"]}
    assert all(not c for c in grille["cells"][parc["vid2"].id].values())


def test_breakdown_shows_instead_of_reserved(parc):
    un = VehicleUnavailability(vehicle_id=parc["vl1"].id, start_at=datetime(2026, 10, 6),
                               end_at=datetime(2026, 10, 6, 23, 59), category="mecanique")
    db.session.add(un)
    db.session.commit()
    with app.test_request_context("/"):
        grille = calendar_grid([parc["vl1"]], [], [], [un], datetime(2026, 10, 5),
                               datetime(2026, 10, 12), None, [])
    assert [i["letter"] for i in grille["cells"][parc["vl1"].id]["2026-10-06"]] == ["I"]


def test_reserved_days_are_not_listed_as_reservations(parc):
    assert calendar_entries(_grille(parc)) == []


def test_month_view_shows_the_legend_and_chips(parc):
    html = _client(parc["jean"]).get("/calendar/month?y=2026&m=10").data.decode()
    assert "cal-chip-reserved" in html
    assert "Usage réservé, hors prêt" in html


def test_mobile_lists_each_reserved_vehicle_once(parc):
    _pret(parc["vl1"], date(2026, 10, 12), date(2026, 10, 16))
    html = _client(parc["jean"]).get("/calendar/month?y=2026&m=10").data.decode()
    mobile = html.split('class="calendar-mobile"')[1]
    bloc = mobile.split("Usage réservé")[1].split("mobile-day-card")[0]
    assert bloc.count("mobile-reservation") == 2
    assert "Prêté du 12/10 au 16/10" in bloc
    assert "Aucun prêt sur la période" in bloc


def test_home_shows_reserved_then_loaned(parc):
    def etat(code):
        return {e["vehicle"].code: e for e in today_overview(NOW)}[code]
    assert etat("VL1")["state"] == "reserved"
    _pret(parc["vl1"], date(2026, 10, 5), date(2026, 10, 9))
    assert etat("VL1")["state"] == "free"
    assert etat("VL1")["loan"] is not None
    html = _client(parc["jean"]).get("/").data.decode()
    assert "Prêté jusqu'au 09/10" in html
    assert "Usage réservé" in html, "VL2 reste réservé"


def test_pdf_explains_reserved_vehicles(parc):
    from flask import render_template
    from datetime import timedelta
    _pret(parc["vl1"], date(2026, 10, 12), date(2026, 10, 16), motif="congés")
    payload = app_module.calendar_payload(datetime(2026, 10, 1), datetime(2026, 11, 1))
    with app.test_request_context("/"):
        html = render_template("pdf_month.html", **payload)
    assert "pastille-reserved" in html
    tableau = html.split("<h2>Véhicules à usage réservé</h2>")[1].split("</table>")[0]
    assert "Chef de centre" in tableau and "du 12/10 au 16/10 (congés)" in tableau
