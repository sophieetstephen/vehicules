"""Export PDF et archivage annuel.

Une réservation répartie sur plusieurs véhicules porte ``vehicle_id = None`` et
ses attributions dans des segments : sans eux, elle était absente des PDF, y
compris de l'archive annuelle qui servait ensuite de justification pour
supprimer les réservations de l'année.
"""

from datetime import datetime, timedelta

import pytest
from flask import render_template

from app import app, reservation_slot_label, _month_year_label
from models import db, User, Vehicle, Reservation, ReservationSegment

START, END = datetime(2026, 3, 1), datetime(2026, 4, 1)


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


def _fixture_segmentee():
    """Jean réserve 2 jours : VL1 le 2 mars, VL2 le 3 mars."""
    u = User(name="Dupont Jean", first_name="Jean", last_name="Dupont", username="dupontj",
             email="j@ex.fr", role=User.ROLE_USER, status="active", password_hash="x")
    v1, v2 = Vehicle(code="VL1", label="Léger 1"), Vehicle(code="VL2", label="Léger 2")
    db.session.add_all([u, v1, v2])
    db.session.commit()
    r = Reservation(user_id=u.id, vehicle_id=None, start_at=datetime(2026, 3, 2, 8),
                    end_at=datetime(2026, 3, 3, 17), status="approved", purpose="Formation JSP")
    db.session.add(r)
    db.session.commit()
    db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=v1.id,
                                      start_at=datetime(2026, 3, 2, 8), end_at=datetime(2026, 3, 2, 17)))
    db.session.add(ReservationSegment(reservation_id=r.id, vehicle_id=v2.id,
                                      start_at=datetime(2026, 3, 3, 8), end_at=datetime(2026, 3, 3, 17)))
    db.session.commit()
    return u, v1, v2, r


def _rendu(**kwargs):
    with app.test_request_context("/"):
        return render_template("pdf_month.html", start=START, end=END,
                               slot_label=reservation_slot_label,
                               month_year_label=_month_year_label,
                               timedelta=timedelta, **kwargs)


def test_pdf_includes_segmented_reservations(ctx):
    u, v1, v2, r = _fixture_segmentee()
    segs = ReservationSegment.query.join(Reservation).all()
    html = _rendu(vehicles=[v1, v2], reservations=[r], segments=segs)
    # Une fois par jour segmenté, donc sur les deux véhicules.
    assert html.count("Formation JSP") == 2
    assert "Dupont" in html


def test_pdf_without_segments_is_still_valid(ctx):
    """Réservation classique attribuée directement : inchangée."""
    u, v1, v2, _ = _fixture_segmentee()
    simple = Reservation(user_id=u.id, vehicle_id=v1.id, start_at=datetime(2026, 3, 10, 8),
                         end_at=datetime(2026, 3, 10, 12), status="approved", purpose="Réunion")
    db.session.add(simple)
    db.session.commit()
    html = _rendu(vehicles=[v1, v2], reservations=[simple], segments=[])
    assert html.count("Réunion") == 1


def test_pdf_does_not_duplicate_partially_segmented_reservation(ctx):
    """Un jour segmenté ne doit pas s'afficher deux fois."""
    u, v1, v2, _ = _fixture_segmentee()
    r = Reservation(user_id=u.id, vehicle_id=v1.id, start_at=datetime(2026, 3, 20, 8),
                    end_at=datetime(2026, 3, 21, 17), status="approved", purpose="Manoeuvre")
    db.session.add(r)
    db.session.commit()
    seg = ReservationSegment(reservation_id=r.id, vehicle_id=v2.id,
                             start_at=datetime(2026, 3, 21, 8), end_at=datetime(2026, 3, 21, 17))
    db.session.add(seg)
    db.session.commit()
    html = _rendu(vehicles=[v1, v2], reservations=[r], segments=[seg])
    # 20 mars sur VL1 (direct) + 21 mars sur VL2 (segment) = 2, pas 3.
    assert html.count("Manoeuvre") == 2


def test_pdf_template_tolerates_missing_segments(ctx):
    """Un appelant qui ne passe pas segments ne doit pas planter."""
    u, v1, v2, r = _fixture_segmentee()
    assert "Planning" in _rendu(vehicles=[v1, v2], reservations=[r])


def test_export_route_passes_segments(ctx):
    """La route d'export mensuel fournit bien les segments au modèle."""
    u, v1, v2, r = _fixture_segmentee()
    admin = User(name="Chef Alex", first_name="Alex", last_name="Chef", username="chefa",
                 email="c@ex.fr", role=User.ROLE_ADMIN, status="active", password_hash="x")
    db.session.add(admin)
    db.session.commit()
    captured = {}
    import app as app_module
    vrai_rendu = app_module.render_template

    def espion(nom, **kw):
        captured.update(kw)
        return vrai_rendu(nom, **kw)

    app_module.render_template = espion
    try:
        client = app.test_client()
        with client.session_transaction() as s:
            s["uid"] = admin.id
            s["pwd_stamp"] = admin.session_stamp(app.config["SECRET_KEY"])
        client.get("/export/pdf/month?y=2026&m=3")
    finally:
        app_module.render_template = vrai_rendu
    assert "segments" in captured, "la route doit transmettre les segments"
    assert len(captured["segments"]) == 2


# --- archivage annuel : la base ne doit plus être purgée par défaut ---------

def test_archive_year_does_not_purge_by_default():
    import tools.archive_year as ay
    import inspect

    source = inspect.getsource(ay.main)
    assert "if args.purge:" in source, "la purge doit être conditionnée"
    assert "--purge" in inspect.getsource(ay.main)

    parser_src = inspect.getsource(ay.main)
    assert "IRREVERSIBLE" in parser_src or "irreversible" in parser_src.lower()


def test_archive_year_service_has_no_purge_flag():
    """Le minuteur du 31 décembre ne doit pas supprimer de réservations."""
    with open("tools/archive_year.service", encoding="utf-8") as fh:
        lignes = fh.read().splitlines()
    commandes = [l for l in lignes if l.strip().startswith("ExecStart=")]
    assert commandes, "le service doit définir une commande"
    for commande in commandes:
        assert "archive_year.py" in commande
        assert "--purge" not in commande, commande
