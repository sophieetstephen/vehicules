#!/usr/bin/env python3
"""Archive yearly planning to PDF and purge old reservations.

This script:
1. Generates PDF exports for each month of the specified year
2. Verifies all 12 PDFs were created successfully
3. Only if all PDFs are OK: purges reservations from that year
4. Removes PDF archives older than the retention period

Usage:
    python tools/archive_year.py [--year YYYY] [--dry-run] [--keep-years N]

Examples:
    # Archive the previous year (default behavior for end-of-year timer)
    python tools/archive_year.py

    # Archive a specific year
    python tools/archive_year.py --year 2024

    # Preview without making changes
    python tools/archive_year.py --dry-run

    # Keep 3 years of archives instead of default 2
    python tools/archive_year.py --keep-years 3
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
ARCHIVE_DIR = os.path.join(ROOT_DIR, "backups", "archives")


def generate_pdf_for_month(year: int, month: int, output_path: str) -> bool:
    """Generate PDF planning for a specific month.

    Returns True if PDF was created successfully.
    """
    if not WEASY_OK:
        print("  ERREUR: WeasyPrint non disponible")
        return False

    from weasyprint import HTML
    from flask import render_template
    from app import (
        Vehicle, Reservation as ReservationModel,
        reservation_slot_label, month_year_label
    )

    # Calculate month boundaries
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    with app.app_context():
        vehicles = Vehicle.query.order_by(Vehicle.code).all()
        reservations = ReservationModel.query.filter(
            ReservationModel.status == "approved",
            ReservationModel.start_at < end,
            ReservationModel.end_at >= start
        ).all()

        html_content = render_template(
            "pdf_month.html",
            vehicles=vehicles,
            reservations=reservations,
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
        default=datetime.now().year - 1,  # Previous year by default
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
    args = parser.parse_args()

    print(f"=== Archivage annuel du planning ===")
    print(f"Annee: {args.year}")
    print(f"Conservation: {args.keep_years} ans")
    if args.dry_run:
        print("Mode: DRY-RUN (aucune modification)")

    # Step 1: Generate PDFs
    archive_success, pdf_count = archive_year(args.year, args.dry_run)

    if not archive_success:
        print(f"\nERREUR: Seulement {pdf_count}/12 PDFs generes.")
        print("Purge annulee par securite.")
        return 1

    print(f"\nSUCCES: {pdf_count}/12 PDFs generes.")

    # Step 2: Purge reservations (only if all PDFs OK)
    purge_year_reservations(args.year, args.dry_run)

    # Step 3: Cleanup old archives
    cleanup_old_archives(args.keep_years, args.dry_run)

    print("\n=== Archivage termine ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
