import re
import secrets
import unicodedata
from datetime import time

# Alphabet sans caractères ambigus (pas de 0/O, 1/l/I) pour éviter les erreurs
# de recopie quand l'identifiant est transmis à l'oral ou sur papier.
_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def slugify_name(value):
    """Return ``value`` lowercased, without accents and keeping only a-z0-9."""

    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_only.lower())


def build_username_base(first_name=None, last_name=None, name=None, email=None):
    """Return the base login identifier: last name + first letter of first name.

    Falls back on the legacy ``name`` column ("Nom Prénom") and finally on the
    local part of the e-mail address so that every existing account receives a
    usable identifier during the migration.
    """

    last = slugify_name(last_name)
    first = slugify_name(first_name)
    if not last and name:
        parts = [slugify_name(p) for p in str(name).split()]
        parts = [p for p in parts if p]
        if parts:
            last = parts[0]
            if not first and len(parts) > 1:
                first = parts[1]
    if last:
        return last + (first[0] if first else "")
    if email and "@" in email:
        local = slugify_name(email.split("@", 1)[0])
        if local:
            return local
    return "utilisateur"


def make_unique_username(base, is_taken):
    """Return ``base`` or ``base2``, ``base3``… until ``is_taken`` is False."""

    candidate = base
    suffix = 2
    while is_taken(candidate):
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def generate_password(groups=3, group_len=4):
    """Return a random password such as ``Kx7m-Rp2v-Q9wT``.

    The password is generated server side with the ``secrets`` module; users
    never choose their own password so that no SDIS mailbox password can ever
    be reused in this application.
    """

    parts = [
        "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(group_len))
        for _ in range(groups)
    ]
    return "-".join(parts)


def reservation_slot_label(reservation, day):
    """Return a human label (Matin/Après-midi/Journée) for reservation on given day."""
    morning_start = time(8, 0)
    morning_end = time(12, 0)
    afternoon_start = time(13, 0)
    afternoon_end = time(17, 0)
    day_date = day.date()
    start_date = reservation.start_at.date()
    end_date = reservation.end_at.date()
    start_time = reservation.start_at.time()
    end_time = reservation.end_at.time()

    if start_date == day_date and end_date == day_date:
        if (
            start_time >= morning_start
            and start_time <= morning_end
            and end_time <= morning_end
        ):
            return "Matin"
        if start_time >= afternoon_start and end_time <= afternoon_end:
            return "Après-midi"
        return "Journée"
    if start_date == day_date:
        if start_time >= afternoon_start:
            return "Après-midi"
        return "Journée"
    if end_date == day_date:
        if end_time <= morning_end:
            return "Matin"
        return "Journée"
    return "Journée"
