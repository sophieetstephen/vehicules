#!/usr/bin/env python3
"""Archive old reservations automatically.

This script archives reservations whose end date has passed by a configurable
number of days. Archived reservations are hidden from the admin management
interface but remain visible in the monthly calendar.

Usage:
    python tools/archive_reservations.py [--days N] [--dry-run]

Examples:
    # Archive reservations ended more than 7 days ago (default)
    python tools/archive_reservations.py

    # Archive reservations ended more than 14 days ago
    python tools/archive_reservations.py --days 14

    # Preview what would be archived without making changes
    python tools/archive_reservations.py --dry-run
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

# Ensure repository root is in import path
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app
from models import db, Reservation

DEFAULT_DAYS = 7


def archive_old_reservations(days: int, dry_run: bool = False) -> int:
    """Archive reservations ended more than `days` ago.

    Args:
        days: Number of days after end_at before archiving
        dry_run: If True, only print what would be archived

    Returns:
        Number of reservations archived (or would be archived)
    """
    cutoff = datetime.now() - timedelta(days=days)

    with app.app_context():
        # Find non-archived reservations that ended before cutoff
        to_archive = Reservation.query.filter(
            Reservation.archived_at.is_(None),
            Reservation.end_at < cutoff
        ).all()

        count = len(to_archive)

        if count == 0:
            print("Aucune reservation a archiver.")
            return 0

        if dry_run:
            print(f"[DRY-RUN] {count} reservation(s) seraient archivee(s):")
            for r in to_archive:
                print(f"  - ID {r.id}: {r.start_at.date()} -> {r.end_at.date()} "
                      f"({r.status}) - {r.purpose or 'sans motif'}")
        else:
            now = datetime.now()
            for r in to_archive:
                r.archived_at = now
            db.session.commit()
            print(f"{count} reservation(s) archivee(s).")

        return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive les reservations dont la date de fin est depassee"
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Nombre de jours apres la fin avant archivage (defaut: {DEFAULT_DAYS})"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Afficher ce qui serait archive sans effectuer de modifications"
    )
    args = parser.parse_args()

    print(f"Archivage des reservations terminees depuis plus de {args.days} jour(s)...")
    archive_old_reservations(args.days, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
