#!/usr/bin/env python3
"""Archive yearly planning to PDF.

This script:
1. Generates PDF exports for each month of the specified year
2. Verifies all 12 PDFs were created successfully
3. Removes PDF archives older than the retention period
4. Only with --purge: deletes that year's reservations from the database

IMPORTANT: the database purge is OFF by default. The reservations stay in the
application so that the planning and the history remain consultable; a year of
reservations weighs only a few hundred kilobytes. Use --purge only if you
really want to delete them, and check the PDFs first.

ATTENTION, en conteneur: les PDF sont ecrits dans le dossier indique par
--output-dir, ARCHIVE_DIR, ou a defaut <depot>/backups/archives. Ce dernier
appartient au conteneur. Avec "docker compose run --rm" il disparait avec lui,
et une reconstruction de l'image emporte celui du conteneur courant. Visez un
chemin monte depuis l'hote. Le script refuse desormais de presenter une telle
execution comme un succes.

Usage:
    python tools/archive_year.py [--year YYYY] [--dry-run] [--keep-years N]
                                 [--output-dir CHEMIN] [--purge]

Examples:
    # Archive the previous year (default behavior for end-of-year timer)
    python tools/archive_year.py

    # Archive a specific year
    python tools/archive_year.py --year 2024

    # Preview without making changes
    python tools/archive_year.py --dry-run

    # Keep 3 years of archives instead of default 2
    python tools/archive_year.py --keep-years 3

    # Also delete the year's reservations from the database (irreversible)
    python tools/archive_year.py --year 2024 --purge
"""

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta

# Ensure repository root is in import path
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app, WEASY_OK
from models import db, Reservation

DEFAULT_KEEP_YEARS = 2

# Destination des PDF. Le chemin par defaut est relatif au depot : lance dans
# un conteneur jetable (docker compose run --rm), il designe un disque detruit
# a la fin de la commande, et les archives disparaissaient sans un mot.
# ARCHIVE_DIR ou --output-dir permettent de viser un dossier monte sur l'hote.
DEFAULT_ARCHIVE_DIR = os.path.join(ROOT_DIR, "backups", "archives")
ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR") or DEFAULT_ARCHIVE_DIR


def default_archive_year(now=None) -> int:
    """Annee archivee sans --year : celle qui vient de se terminer.

    Le minuteur tourne le 1er janvier ; lance le 31 decembre, ce calcul
    visait l'avant-derniere annee.
    """

    return (now or datetime.now()).year - 1


def destination_is_volatile(path: str, in_container: bool | None = None) -> bool:
    """Les PDF vont-ils dans le disque jetable d'un conteneur ?

    Un « docker compose run --rm » ecrit dans un conteneur detruit a la fin de
    la commande. Le script annoncait alors douze reussites et ne laissait rien
    derriere lui. Un dossier monte depuis l'hote apparait comme point de
    montage a l'interieur du conteneur : on remonte les parents pour le voir.
    """

    if in_container is None:
        in_container = os.path.exists("/.dockerenv")
    if not in_container:
        return False

    # La racine est toujours un point de montage — c'est justement le disque
    # jetable du conteneur : on remonte jusqu'a elle sans la compter.
    chemin = os.path.abspath(path)
    while chemin != os.path.sep:
        if os.path.ismount(chemin):
            return False
        chemin = os.path.dirname(chemin)
    return True


def generate_pdf_for_month(year: int, month: int, output_path: str) -> bool:
    """Generate PDF planning for a specific month.

    Returns True if PDF was created successfully.
    """
    if not WEASY_OK:
        print("  ERREUR: WeasyPrint non disponible")
        return False

    from weasyprint import HTML
    from flask import render_template
    from sqlalchemy import or_
    from app import (
        Vehicle, Reservation as ReservationModel,
        ReservationSegment as SegmentModel,
        VehicleUnavailability as UnavailabilityModel,
        VehicleLoan as LoanModel,
        reservation_slot_label,
        # app.py n'a jamais exporte ce nom sans tiret bas : l'import echouait,
        # et l'archive annuelle n'a donc jamais produit le moindre PDF.
        _month_year_label as month_year_label,
    )

    # Calculate month boundaries
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    # Contexte de requete et non simple contexte d'application : le gabarit
    # appelle url_for() pour sa feuille de style, ce qui echoue sinon.
    with app.test_request_context("/"):
        vehicles = Vehicle.query.order_by(Vehicle.code).all()
        reservations = ReservationModel.query.filter(
            ReservationModel.status == "approved",
            ReservationModel.start_at < end,
            ReservationModel.end_at >= start
        ).all()

        # Sans les segments, toute reservation repartie sur plusieurs vehicules
        # serait absente de l'archive (son vehicle_id vaut None).
        segments = SegmentModel.query.join(ReservationModel).filter(
            ReservationModel.status == "approved",
            SegmentModel.start_at < end,
            SegmentModel.end_at >= start
        ).all()

        # Sans elles, l'archive laisse croire qu'un vehicule etait disponible
        # alors qu'il etait en panne ou en entretien. C'est la trace
        # permanente : elle doit refleter le mois tel qu'il a ete vecu.
        unavailabilities = UnavailabilityModel.query.filter(
            UnavailabilityModel.start_at < end,
            or_(
                UnavailabilityModel.end_at.is_(None),
                UnavailabilityModel.end_at >= start,
            ),
        ).all()

        # Sans eux, un vehicule a usage reserve paraitrait reserve meme les
        # jours ou il etait prete.
        loans = LoanModel.query.filter(
            LoanModel.start_at < end,
            LoanModel.end_at >= start,
        ).all()

        html_content = render_template(
            "pdf_month.html",
            vehicles=vehicles,
            reservations=reservations,
            segments=segments,
            unavailabilities=unavailabilities,
            loans=loans,
            start=start,
            end=end,
            slot_label=reservation_slot_label,
            month_year_label=month_year_label,
            timedelta=timedelta
        )

        try:
            HTML(string=html_content, base_url=app.config.get("BASE_URL", "")).write_pdf(output_path)
            # Verify file exists and has content
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return True
            else:
                print(f"  ERREUR: PDF cree mais trop petit ou inexistant")
                return False
        except Exception as e:
            print(f"  ERREUR lors de la generation: {e}")
            return False


def archive_year(year: int, dry_run: bool = False) -> tuple[bool, int]:
    """Generate PDF archives for all months of the year.

    Returns:
        Tuple of (success: bool, pdf_count: int)
    """
    year_dir = os.path.join(ARCHIVE_DIR, str(year))

    if not dry_run:
        os.makedirs(year_dir, exist_ok=True)

    print(f"\nGeneration des PDFs pour l'annee {year}...")

    success_count = 0
    for month in range(1, 13):
        pdf_name = f"planning_{year}-{month:02d}.pdf"
        pdf_path = os.path.join(year_dir, pdf_name)

        if dry_run:
            print(f"  [DRY-RUN] Genererait: {pdf_name}")
            success_count += 1
        else:
            print(f"  Generation: {pdf_name}...", end=" ")
            if generate_pdf_for_month(year, month, pdf_path):
                size_kb = os.path.getsize(pdf_path) / 1024
                print(f"OK ({size_kb:.1f} Ko)")
                success_count += 1
            else:
                print("ECHEC")

    success = success_count == 12
    return success, success_count


def purge_year_reservations(year: int, dry_run: bool = False) -> int:
    """Delete all reservations from the specified year.

    Returns number of reservations deleted.
    """
    start_of_year = datetime(year, 1, 1)
    end_of_year = datetime(year, 12, 31, 23, 59, 59)

    with app.app_context():
        # Find reservations that ended within the year
        to_delete = Reservation.query.filter(
            Reservation.end_at >= start_of_year,
            Reservation.end_at <= end_of_year
        ).all()

        count = len(to_delete)

        if count == 0:
            print(f"\nAucune reservation a purger pour {year}.")
            return 0

        if dry_run:
            print(f"\n[DRY-RUN] {count} reservation(s) seraient supprimee(s) pour {year}:")
            for r in to_delete[:5]:  # Show first 5
                print(f"  - ID {r.id}: {r.start_at.date()} -> {r.end_at.date()}")
            if count > 5:
                print(f"  ... et {count - 5} autres")
        else:
            for r in to_delete:
                db.session.delete(r)
            db.session.commit()
            print(f"\n{count} reservation(s) supprimee(s) pour {year}.")

        return count


def cleanup_old_archives(keep_years: int, dry_run: bool = False) -> int:
    """Remove PDF archives older than keep_years.

    Returns number of year directories removed.
    """
    if not os.path.exists(ARCHIVE_DIR):
        return 0

    current_year = datetime.now().year
    cutoff_year = current_year - keep_years
    removed = 0

    print(f"\nNettoyage des archives anterieures a {cutoff_year}...")

    for dirname in os.listdir(ARCHIVE_DIR):
        dir_path = os.path.join(ARCHIVE_DIR, dirname)
        if not os.path.isdir(dir_path):
            continue

        try:
            year = int(dirname)
            if year < cutoff_year:
                if dry_run:
                    print(f"  [DRY-RUN] Supprimerait: {dirname}/")
                else:
                    shutil.rmtree(dir_path)
                    print(f"  Supprime: {dirname}/")
                removed += 1
        except ValueError:
            continue  # Not a year directory

    if removed == 0:
        print("  Aucune archive a supprimer.")

    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive le planning annuel en PDF et purge les anciennes reservations"
    )
    parser.add_argument(
        "--year", "-y",
        type=int,
        default=default_archive_year(),
        help="Annee a archiver (defaut: annee precedente)"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Afficher ce qui serait fait sans effectuer de modifications"
    )
    parser.add_argument(
        "--keep-years", "-k",
        type=int,
        default=DEFAULT_KEEP_YEARS,
        help=f"Nombre d'annees d'archives a conserver (defaut: {DEFAULT_KEEP_YEARS})"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Dossier ou ecrire les PDF (defaut: ARCHIVE_DIR ou "
             "<depot>/backups/archives). A l'interieur d'un conteneur, visez "
             "un chemin monte depuis l'hote, sinon les fichiers sont perdus."
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Supprimer aussi les reservations de l'annee dans la base "
             "(IRREVERSIBLE, desactive par defaut : l'historique reste consultable)"
    )
    args = parser.parse_args()

    global ARCHIVE_DIR
    if args.output_dir:
        ARCHIVE_DIR = args.output_dir

    print(f"=== Archivage annuel du planning ===")
    print(f"Annee: {args.year}")
    print(f"Conservation: {args.keep_years} ans")
    # Chemin absolu affiche des le depart : sans lui, on ne savait pas ou les
    # fichiers etaient partis.
    print(f"Destination: {os.path.abspath(ARCHIVE_DIR)}")

    volatile = destination_is_volatile(ARCHIVE_DIR)
    if volatile:
        print("\n  *** ATTENTION ***")
        print("  Ce dossier n'est pas monte depuis l'hote : il appartient au")
        print("  conteneur et disparaitra avec lui. Relancez la commande avec")
        print("  --output-dir vers un chemin monte, sinon les PDF seront perdus.")
    if args.dry_run:
        print("Mode: DRY-RUN (aucune modification)")

    # Step 1: Generate PDFs
    archive_success, pdf_count = archive_year(args.year, args.dry_run)

    if not archive_success:
        print(f"\nERREUR: Seulement {pdf_count}/12 PDFs generes.")
        if args.purge:
            print("Purge annulee par securite.")
        return 1

    print(f"\nSUCCES: {pdf_count}/12 PDFs generes.")

    # Des PDF qui disparaitront avec le conteneur ne sont pas une archive :
    # rien ne doit etre supprime sur leur foi, ni les reservations de
    # l'annee, ni les anciennes archives.
    if volatile:
        print("\n*** Les PDF ont ete ecrits dans le conteneur et seront perdus. ***")
        if args.purge:
            print("Purge annulee par securite : la base n'a pas ete modifiee.")
        print("Relancez avec --output-dir vers un dossier monte depuis l'hote.")
        return 1

    # Step 2: Purge reservations - uniquement sur demande explicite.
    # Par defaut l'historique reste dans l'application (quelques centaines de
    # kilo-octets par an) et reste consultable dans le planning.
    if args.purge:
        purge_year_reservations(args.year, args.dry_run)
    else:
        print("\nBase de donnees inchangee (utilisez --purge pour supprimer "
              "les reservations de l'annee).")

    # Step 3: Cleanup old archives
    cleanup_old_archives(args.keep_years, args.dry_run)

    print("\n=== Archivage termine ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
