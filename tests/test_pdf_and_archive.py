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


# --- indisponibilités : absentes des PDF jusqu'ici --------------------------
#
# Le gabarit refaisait ses propres boucles sur les réservations. Les
# indisponibilités, ajoutées plus tard au planning affiché, ne sont jamais
# arrivées jusqu'ici : ni l'export mensuel ni l'archive annuelle ne les
# chargeaient. Un véhicule en panne apparaissait donc libre sur le papier.

from models import VehicleUnavailability


def _indispo(vehicle, debut, fin=None, categorie="mecanique", details=None):
    un = VehicleUnavailability(vehicle_id=vehicle.id, start_at=debut, end_at=fin,
                               category=categorie, details=details)
    db.session.add(un)
    db.session.commit()
    return un


def test_pdf_marks_unavailable_days(ctx):
    _, v1, v2, _ = _fixture_segmentee()
    _indispo(v1, datetime(2026, 3, 10), datetime(2026, 3, 12), details="embrayage")
    html = _rendu(vehicles=[v1, v2], reservations=[], segments=[],
                  unavailabilities=list(VehicleUnavailability.query.all()))
    grille = html.split("<tbody>")[1].split("</tbody>")[0]
    # Trois jours couverts : 10, 11 et 12 mars.
    assert grille.count("pastille-unav") == 3


def test_pdf_marks_the_right_vehicle(ctx):
    """La pastille doit tomber sur la ligne du véhicule en panne."""
    _, v1, v2, _ = _fixture_segmentee()
    _indispo(v1, datetime(2026, 3, 10), datetime(2026, 3, 10))
    html = _rendu(vehicles=[v1, v2], reservations=[], segments=[],
                  unavailabilities=list(VehicleUnavailability.query.all()))
    # Couper a </tr> : sinon la derniere ligne englobe la legende, qui porte
    # elle aussi une pastille.
    lignes = [bloc.split("</tr>")[0] for bloc in html.split('class="vehicle-row"')[1:]]
    ligne_v1 = [l for l in lignes if "VL1" in l][0]
    ligne_v2 = [l for l in lignes if "VL2" in l][0]
    assert "pastille-unav" in ligne_v1
    assert "pastille-unav" not in ligne_v2


def test_pdf_recaps_reason_and_period(ctx):
    """La case ne tient qu'une pastille : le motif est récapitulé dessous."""
    _, v1, v2, _ = _fixture_segmentee()
    _indispo(v1, datetime(2026, 3, 10), datetime(2026, 3, 12), details="embrayage")
    html = _rendu(vehicles=[v1, v2], reservations=[], segments=[],
                  unavailabilities=list(VehicleUnavailability.query.all()))
    recap = html.split("<h2>Indisponibilités</h2>")[1]
    assert "Panne mécanique – embrayage" in recap
    assert "du 10/03/2026" in recap and "au 12/03/2026" in recap


def test_pdf_handles_open_ended_unavailability(ctx):
    _, v1, v2, _ = _fixture_segmentee()
    _indispo(v1, datetime(2026, 3, 25), None, categorie="carrosserie")
    html = _rendu(vehicles=[v1, v2], reservations=[], segments=[],
                  unavailabilities=list(VehicleUnavailability.query.all()))
    # Du 25 au 31 mars inclus.
    grille = html.split("<tbody>")[1].split("</tbody>")[0]
    assert grille.count("pastille-unav") == 7
    assert "jusqu'à nouvel ordre" in html


def test_pdf_template_tolerates_missing_unavailabilities(ctx):
    """Un appelant qui ne les passe pas ne doit pas planter."""
    _, v1, v2, r = _fixture_segmentee()
    html = _rendu(vehicles=[v1, v2], reservations=[r], segments=[])
    assert "Planning" in html
    assert "<h2>Indisponibilités</h2>" not in html


def _espionner_rendu(monkeypatch):
    """Capturer les arguments passés au gabarit PDF."""
    import flask
    import app as app_module
    captures = {}
    vrai = flask.render_template

    def espion(nom, **kw):
        if nom == "pdf_month.html":
            captures.update(kw)
        return vrai(nom, **kw)

    monkeypatch.setattr(flask, "render_template", espion)
    monkeypatch.setattr(app_module, "render_template", espion)
    return captures


def test_export_route_passes_unavailabilities(ctx, monkeypatch):
    _, v1, _, _ = _fixture_segmentee()
    _indispo(v1, datetime(2026, 3, 10), datetime(2026, 3, 12), details="embrayage")
    admin = User(name="Chef Alex", first_name="Alex", last_name="Chef", username="chefa",
                 email="c@ex.fr", role=User.ROLE_ADMIN, status="active", password_hash="x")
    db.session.add(admin)
    db.session.commit()

    captures = _espionner_rendu(monkeypatch)
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = admin.id
        s["pwd_stamp"] = admin.session_stamp(app.config["SECRET_KEY"])
    reponse = client.get("/export/pdf/month?y=2026&m=3")

    assert reponse.status_code == 200
    assert reponse.mimetype == "application/pdf"
    assert len(captures.get("unavailabilities", [])) == 1


def test_annual_archive_passes_unavailabilities(ctx, monkeypatch, tmp_path):
    """L'archive est la trace permanente : elle doit montrer le mois tel qu'il
    a été vécu, pannes comprises."""
    import tools.archive_year as ay

    _, v1, _, _ = _fixture_segmentee()
    _indispo(v1, datetime(2026, 3, 10), datetime(2026, 3, 12), details="embrayage")

    captures = _espionner_rendu(monkeypatch)
    monkeypatch.setattr(ay, "app", app)
    ok = ay.generate_pdf_for_month(2026, 3, str(tmp_path / "mars.pdf"))

    assert ok, "le PDF d'archive n'a pas été produit"
    assert len(captures.get("unavailabilities", [])) == 1


def test_archive_tool_imports_match_the_application():
    """L'outil importait « month_year_label », un nom que app.py n'a jamais
    exporté sans tiret bas : l'archive annuelle plantait dès l'import et
    n'avait donc jamais produit le moindre PDF."""
    import ast
    import inspect
    import textwrap

    import app as app_module
    import tools.archive_year as ay

    arbre = ast.parse(textwrap.dedent(inspect.getsource(ay.generate_pdf_for_month)))
    manquants = [
        alias.name
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.ImportFrom) and noeud.module == "app"
        for alias in noeud.names
        if not hasattr(app_module, alias.name)
    ]
    assert not manquants, f"noms absents de app.py : {manquants}"


def test_pdf_badges_keep_their_colour_without_internet():
    """Les couleurs venaient de la feuille Bootstrap, téléchargée au moment de
    produire le PDF : sans accès au CDN, les pastilles devenaient invisibles
    sur le papier."""
    import pathlib

    gabarit = pathlib.Path("templates/pdf_month.html").read_text(encoding="utf-8")
    style = gabarit.split("<style>")[1].split("</style>")[0]
    assert ".pastille-res{background:#15803d}" in style
    assert ".pastille-unav{background:#343a40}" in style


# --- où atterrissent les PDF -------------------------------------------------
#
# Lancé par « docker compose run --rm », le script écrivait dans un conteneur
# détruit à la fin de la commande. Il annonçait douze réussites et ne laissait
# rien derrière lui : les vingt-quatre PDF d'archive avaient disparu.

def test_archive_directory_can_be_chosen(tmp_path, monkeypatch):
    """Sans cela, impossible de viser un dossier monté depuis l'hôte."""
    import tools.archive_year as ay

    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "ailleurs"))
    import importlib

    recharge = importlib.reload(ay)
    try:
        assert recharge.ARCHIVE_DIR == str(tmp_path / "ailleurs")
    finally:
        monkeypatch.delenv("ARCHIVE_DIR", raising=False)
        importlib.reload(ay)


def test_output_dir_option_exists():
    import inspect

    import tools.archive_year as ay

    source = inspect.getsource(ay.main)
    assert '"--output-dir"' in source
    assert "ARCHIVE_DIR = args.output_dir" in source


def test_volatile_destination_is_detected(tmp_path, monkeypatch):
    """Dans un conteneur, un dossier qui n'est monté de nulle part est volatil.

    ``ismount`` est neutralisé : la machine de test a ses propres montages
    (/tmp en est un), qui n'ont rien à voir avec ceux du conteneur.
    """
    import tools.archive_year as ay

    monkeypatch.setattr(ay.os.path, "ismount", lambda p: False)
    cible = tmp_path / "backups" / "archives"
    assert ay.destination_is_volatile(str(cible), in_container=True) is True


def test_mounted_destination_is_accepted(tmp_path, monkeypatch):
    import tools.archive_year as ay

    cible = tmp_path / "monte" / "archives"
    cible.mkdir(parents=True)
    vrai_ismount = ay.os.path.ismount
    monkeypatch.setattr(
        ay.os.path, "ismount",
        lambda p: str(p) == str(tmp_path / "monte") or vrai_ismount(p),
    )
    assert ay.destination_is_volatile(str(cible), in_container=True) is False


def test_outside_a_container_nothing_is_volatile(tmp_path):
    """Sur le Raspberry directement, le chemin relatif est parfaitement bon."""
    import tools.archive_year as ay

    assert ay.destination_is_volatile(str(tmp_path), in_container=False) is False


def test_volatile_run_reports_failure():
    """Le script doit sortir en erreur, pas annoncer un succès trompeur."""
    import inspect

    import tools.archive_year as ay

    source = inspect.getsource(ay.main)
    fin = source.split("if volatile:")[-1]
    assert "return 1" in fin, "une archive perdue ne doit pas passer pour un succès"


# --- des lignes assez basses pour qu'une page ne les coupe pas --------------
#
# Signalé sur un export réel : la ligne du VTP était tranchée horizontalement,
# « VTP / Gouest » en bas d'une page et « véhicule 9 places » en haut de la
# suivante. Les cases portaient le créneau, le nom et le motif sur quatre à
# cinq lignes ; WeasyPrint ne sait pas garder une ligne de tableau entière, ni
# avec break-inside ni avec page-break-inside. La seule correction fiable est
# de raccourcir les lignes.

def test_month_is_one_single_grid(ctx):
    """Le mois était coupé en deux quinzaines, sur deux pages : une
    réservation à cheval sur le 15 apparaissait en deux morceaux."""
    _, v1, v2, _ = _fixture_segmentee()
    html = _rendu(vehicles=[v1, v2], reservations=[], segments=[])
    assert html.count('<table class="planning-table">') == 1
    grille = html.split('<table class="planning-table">')[1].split("</table>")[0]
    for jour in ("01", "15", "16", "31"):
        assert f"<br>{jour}" in grille, jour


def test_grid_cell_holds_only_a_badge(ctx):
    """C'est ce qui garde les lignes basses : aucun texte libre dans la case."""
    u, v1, v2, _ = _fixture_segmentee()
    r = Reservation(user_id=u.id, vehicle_id=v1.id, start_at=datetime(2026, 3, 5, 8),
                    end_at=datetime(2026, 3, 5, 12), status="approved",
                    purpose="Transport de materiel encombrant")
    db.session.add(r)
    db.session.commit()
    html = _rendu(vehicles=[v1, v2], reservations=[r], segments=[])
    grille = html.split('<table class="planning-table">')[1].split("</table>")[0]
    assert "pastille-res" in grille
    assert "Transport de materiel encombrant" not in grille
    assert "Dupont" not in grille
    assert "Matin" not in grille


def test_details_are_listed_below(ctx):
    u, v1, v2, _ = _fixture_segmentee()
    r = Reservation(user_id=u.id, vehicle_id=v1.id, start_at=datetime(2026, 3, 5, 8),
                    end_at=datetime(2026, 3, 5, 12), status="approved",
                    purpose="Transport de materiel")
    db.session.add(r)
    db.session.commit()
    html = _rendu(vehicles=[v1, v2], reservations=[r], segments=[])
    detail = html.split("<h2>Réservations du mois</h2>")[1]
    assert "VL1" in detail
    assert "Jean Dupont" in detail
    assert "le 05/03" in detail and "Matin" in detail
    assert "Transport de materiel" in detail


def test_consecutive_days_make_one_line(ctx):
    """Une réservation de trois jours ne doit pas produire trois lignes."""
    u, v1, v2, _ = _fixture_segmentee()
    r = Reservation(user_id=u.id, vehicle_id=v1.id, start_at=datetime(2026, 3, 5, 8),
                    end_at=datetime(2026, 3, 7, 17), status="approved", purpose="Stage")
    db.session.add(r)
    db.session.commit()
    html = _rendu(vehicles=[v1, v2], reservations=[r], segments=[])
    detail = html.split("<h2>Réservations du mois</h2>")[1]
    assert detail.count("Stage") == 1
    assert "du 05/03 au 07/03" in detail


def test_partially_reassigned_reservation_appears_on_both_vehicles(ctx):
    """Le jour repris par un autre véhicule d'un côté, le reste de l'autre.

    Une première version parcourait réservations et segments séparément et
    perdait purement et simplement les jours non réattribués.
    """
    u, v1, v2, _ = _fixture_segmentee()
    r = Reservation(user_id=u.id, vehicle_id=v1.id, start_at=datetime(2026, 3, 20, 8),
                    end_at=datetime(2026, 3, 22, 17), status="approved", purpose="Renfort")
    db.session.add(r)
    db.session.commit()
    seg = ReservationSegment(reservation_id=r.id, vehicle_id=v2.id,
                             start_at=datetime(2026, 3, 21, 8), end_at=datetime(2026, 3, 21, 17))
    db.session.add(seg)
    db.session.commit()

    html = _rendu(vehicles=[v1, v2], reservations=[r], segments=[seg])
    detail = html.split("<h2>Réservations du mois</h2>")[1]
    lignes = [l for l in detail.split("<tr>") if "Renfort" in l]
    assert len(lignes) == 3, "le 20 sur VL1, le 21 sur VL2, le 22 sur VL1"
    assert any("VL2" in l and "le 21/03" in l for l in lignes)
    assert sum(1 for l in lignes if "VL1" in l) == 2


def test_weekday_letters_are_unambiguous(ctx):
    """Une seule initiale confondait mardi et mercredi."""
    _, v1, v2, _ = _fixture_segmentee()
    html = _rendu(vehicles=[v1, v2], reservations=[], segments=[])
    entete = html.split("<thead>")[1].split("</thead>")[0]
    for deux_lettres in ("lu", "ma", "me", "je", "ve", "sa", "di"):
        assert f"{deux_lettres}<br>" in entete, deux_lettres


def test_annual_archive_passes_loans(ctx, monkeypatch, tmp_path):
    """Sans les prêts, un véhicule à usage réservé paraîtrait réservé même
    les jours où il était prêté — dans la trace permanente."""
    import tools.archive_year as ay
    from models import VehicleLoan

    _, v1, _, _ = _fixture_segmentee()
    v1.reserved_for = "Chef de centre"
    db.session.add(VehicleLoan(vehicle_id=v1.id, start_at=datetime(2026, 3, 9),
                               end_at=datetime(2026, 3, 13, 23, 59, 59)))
    db.session.commit()

    captures = _espionner_rendu(monkeypatch)
    monkeypatch.setattr(ay, "app", app)
    assert ay.generate_pdf_for_month(2026, 3, str(tmp_path / "mars.pdf"))
    assert len(captures.get("loans", [])) == 1
