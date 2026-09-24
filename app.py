#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import json
import locale
import os
import re
import secrets
import sys
import tempfile
# Signature: AS-2024-6f9e3c42
from urllib.parse import quote as _urlquote
from functools import wraps
import click
from collections.abc import Iterable
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import (
    Flask,
    request,
    redirect,
    render_template,
    flash,
    session,
    url_for,
    abort,
    send_file,
    send_from_directory,
    jsonify,
    has_request_context,
    make_response,
)
from datetime import datetime, timedelta, time
from io import BytesIO
from forms import (
    LoginForm,
    NewUserForm,
    NewRequestForm,
    UserForm,
    NotificationSettingsForm,
    ContactForm,
    UnavailabilityForm,
    LoanForm,
)
from wtforms.validators import DataRequired, Length
from models import (
    db,
    User,
    Vehicle,
    VehicleLoan,
    Reservation,
    ReservationSegment,
    NotificationSettings,
    VehicleUnavailability,
    LoginAttempt,
    CredentialHandoff,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, case
from sqlalchemy import event as sa_event
from sqlalchemy.engine import Engine
from notify import send_mail_msmtp, check_mail_login
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from utils import reservation_slot_label

ACCOUNT_REVIEW_RECIPIENTS = {"salexandre@sdis62.fr"}

# Statuts qui ne bloquent plus un véhicule.
INACTIVE_STATUSES = ("rejected", "cancelled")


def _normalize_email_candidates(*candidates):
    """Return a deterministic list of non-empty email addresses.

    The helper accepts nested iterables or single values, strips surrounding
    whitespace and lowercases the address so that comparisons and deduplication
    remain reliable even if the input mixes cases or trailing spaces. ``None``
    values or empty strings are ignored entirely.
    """

    normalized = []

    def _flatten(value):
        if value is None:
            return
        if isinstance(value, str):
            email = value.strip()
        elif isinstance(value, Iterable):
            for item in value:
                _flatten(item)
            return
        else:
            email = str(value).strip()
        if not email:
            return
        normalized.append(email.lower())

    for candidate in candidates:
        _flatten(candidate)

    seen = set()
    deduped = []
    for email in normalized:
        if email in seen:
            continue
        seen.add(email)
        deduped.append(email)
    return deduped


def _coerce_int_ids(values):
    """Return a list of integers from an iterable of arbitrary values."""

    result = []
    if not values:
        return result

    def _extend_from_iterable(iterable):
        for entry in iterable:
            result.extend(_coerce_int_ids([entry]))

    for value in values:
        if value is None:
            continue
        if isinstance(value, int):
            result.append(value)
            continue
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            if text.startswith("[") and text.endswith("]"):
                try:
                    decoded = json.loads(text)
                except (TypeError, ValueError):
                    pass
                else:
                    if isinstance(decoded, list):
                        _extend_from_iterable(decoded)
                        continue
                    _extend_from_iterable([decoded])
                    continue
            if "," in text:
                parts = [part.strip() for part in text.split(",") if part.strip()]
                if parts:
                    _extend_from_iterable(parts)
                    continue
            try:
                result.append(int(text))
            except ValueError:
                continue
            continue
        if isinstance(value, Iterable):
            _extend_from_iterable(value)
            continue
        try:
            int_value = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        result.append(int_value)
    return result


def _selected_notification_recipients():
    """Return active admin e-mails explicitly selected in notification settings."""

    settings = NotificationSettings.query.first()
    if not settings or not settings.notify_user_ids:
        return []
    notify_ids = _coerce_int_ids(settings.notify_user_ids)
    if not notify_ids:
        return []
    users = (
        User.query.filter(
            User.id.in_(notify_ids),
            User.status == "active",
        )
        .with_entities(User.email)
        .all()
    )
    return [email for (email,) in users if email]


def admin_notification_recipients(*, fallback_when_empty=True, include_account_review=False):
    """Return admin notification addresses honouring the settings page.

    ``fallback_when_empty`` controls whether the legacy configuration lists
    (``SUPERADMIN_EMAILS``/``ADMIN_EMAILS``) should be used when no checkbox is
    ticked.  ``include_account_review`` injects the hard coded account-review
    mailbox so that user creation notifications always reach the supervision
    team even if they are not part of the selectable list.
    """

    selected = _selected_notification_recipients()
    extras = ACCOUNT_REVIEW_RECIPIENTS if include_account_review else []
    if selected:
        return _normalize_email_candidates(selected, extras)
    if fallback_when_empty:
        return _normalize_email_candidates(
            app.config.get("SUPERADMIN_EMAILS", []) or [],
            app.config.get("ADMIN_EMAILS", []) or [],
            extras,
        )
    return _normalize_email_candidates(extras)

try:
    from weasyprint import HTML
    WEASY_OK = True
except Exception:
    HTML = None
    WEASY_OK = False

# --- Bootstrap sys.path sûr (utile si lancé hors /opt/vehicules)
_here = os.path.dirname(__file__) or "."
for _p in ("/opt/vehicules", _here):
    if _p and _p not in sys.path:
        sys.path.append(_p)

# Config minimale (utilise config.Config si dispo)
try:
    from config import Config
except Exception:
    def _fallback_secret_key():
        key = os.environ.get("SECRET_KEY")
        if key:
            return key
        if os.environ.get("FLASK_ENV") == "development" or os.environ.get("FLASK_DEBUG"):
            return "dev-secret-insecure"
        raise RuntimeError("SECRET_KEY must be set in production")

    class Config:
        SECRET_KEY = _fallback_secret_key()
        WTF_CSRF_ENABLED = True

app = Flask(__name__)
app.config.from_object(Config)

# Derrière Caddy, l'adresse du client arrive dans X-Forwarded-For. On en
# retenait la première valeur — celle que le client peut écrire lui-même : il
# pouvait changer d'adresse apparente à chaque essai et contourner la limite
# de tentatives de connexion par adresse. ProxyFix retient la valeur ajoutée
# par le proxy, la seule fiable. PROXY_COUNT : nombre de proxys devant
# l'application (Caddy seul : 1).
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=int(os.environ.get("PROXY_COUNT", "1")),
    x_proto=int(os.environ.get("PROXY_COUNT", "1")),
)
csrf = CSRFProtect(app)

_storage_root = app.instance_path
try:
    os.makedirs(_storage_root, exist_ok=True)
except PermissionError:
    _fallback_root = os.path.join(tempfile.gettempdir(), "vehicules-instance")
    os.makedirs(_fallback_root, exist_ok=True)
    app.logger.warning(
        "Instance path '%s' is not writable. Using fallback '%s' instead.",
        _storage_root,
        _fallback_root,
    )
    _storage_root = _fallback_root

_database_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
if _database_uri and _database_uri.startswith("sqlite:///"):
    _db_path = _database_uri.replace("sqlite:///", "", 1)
    if _db_path and not _db_path.startswith(":"):
        if not os.path.isabs(_db_path):
            _db_path = os.path.join(_storage_root, _db_path)
        _db_dir = os.path.dirname(_db_path)
        try:
            if _db_dir:
                os.makedirs(_db_dir, exist_ok=True)
        except PermissionError:
            _fallback_path = os.path.join(
                _storage_root, os.path.basename(_db_path) or "vehicules.db"
            )
            os.makedirs(os.path.dirname(_fallback_path), exist_ok=True)
            app.logger.warning(
                "Database directory '%s' is not writable. Falling back to '%s'.",
                _db_dir,
                _fallback_path,
            )
            _db_path = _fallback_path
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_db_path}"
db.init_app(app)
Migrate(app, db)


@sa_event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, connection_record):
    """Faire respecter les références par SQLite lui-même.

    Exécuté à l'ouverture de chaque connexion, donc hors de toute transaction :
    à l'intérieur d'une transaction, SQLite ignorerait la consigne. Les
    migrations la retirent le temps de recréer les tables (migrations/env.py).
    """

    if not app.config.get("SQLITE_FOREIGN_KEYS", True):
        return
    if "sqlite" not in type(dbapi_connection).__module__:
        return
    curseur = dbapi_connection.cursor()
    curseur.execute("PRAGMA foreign_keys=ON")
    curseur.close()

try:
    locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
except locale.Error:
    try:
        locale.setlocale(locale.LC_TIME, "fr_FR")
    except locale.Error:
        pass

_FRENCH_WEEKDAY_ABBRS = ("lun", "mar", "mer", "jeu", "ven", "sam", "dim")
_FRENCH_WEEKDAY_SET = set(_FRENCH_WEEKDAY_ABBRS)
_FRENCH_MONTH_BY_NUMBER = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}
_FRENCH_MONTH_NAMES = set(_FRENCH_MONTH_BY_NUMBER.values())
_ENGLISH_TO_FRENCH_MONTHS = {
    "january": "janvier",
    "february": "février",
    "march": "mars",
    "april": "avril",
    "may": "mai",
    "june": "juin",
    "july": "juillet",
    "august": "août",
    "september": "septembre",
    "october": "octobre",
    "november": "novembre",
    "december": "décembre",
}


def _weekday_abbr(dt):
    if not dt:
        return ""
    label = dt.strftime("%a")
    if label:
        normalized = label.lower().strip(".")
        if normalized in _FRENCH_WEEKDAY_SET:
            return normalized
    return _FRENCH_WEEKDAY_ABBRS[dt.weekday()]


def _month_year_label(dt):
    if not dt:
        return ""
    month_name = dt.strftime("%B") or ""
    normalized = month_name.strip().lower()
    if normalized in _FRENCH_MONTH_NAMES:
        month = normalized
    else:
        month = _ENGLISH_TO_FRENCH_MONTHS.get(normalized)
        if not month:
            month = _FRENCH_MONTH_BY_NUMBER.get(dt.month, normalized)
    return f"{month} {dt.year}" if month else dt.strftime("%B %Y")


_static_versions = {}


def static_version(filename):
    """Empreinte du contenu d'un fichier statique, calculée une fois."""

    if filename not in _static_versions:
        chemin = os.path.join(app.static_folder, filename)
        try:
            with open(chemin, "rb") as fichier:
                _static_versions[filename] = hashlib.md5(fichier.read()).hexdigest()[:8]
        except OSError:
            _static_versions[filename] = "0"
    return _static_versions[filename]


def static_url(filename):
    """Adresse d'un fichier statique, suffixée par l'empreinte de son contenu.

    Sans cela, le service worker ressert indéfiniment la version en cache :
    une feuille de style corrigée n'atteignait jamais les navigateurs déjà
    venus. Une modification change l'empreinte, donc l'adresse, donc le cache.
    """

    return f"{url_for('static', filename=filename)}?v={static_version(filename)}"


@app.context_processor
def _inject_locale_helpers():
    return {
        "weekday_abbr": _weekday_abbr,
        "month_year_label": _month_year_label,
        "static_url": static_url,
        # Défini plus bas dans le fichier : la résolution a lieu à l'appel.
        "calendar_grid": calendar_grid,
        "can_act_on_account": can_act_on_account,
        "calendar_entries": calendar_entries,
    }


def delete_reservations(query):
    """Supprimer des réservations **et leurs segments**. Retourne le nombre supprimé.

    ``Query.delete()`` émet un seul ordre SQL et ne déclenche pas la cascade de
    l'ORM : les segments survivraient à leur réservation. Or un segment
    orphelin est invisible dans le planning (qui fait une jointure sur
    ``Reservation``) mais reste vu par ``has_conflict`` : le véhicule
    apparaîtrait libre tout en étant impossible à attribuer, définitivement.
    Les segments sont donc supprimés explicitement d'abord.
    """

    ids = [row[0] for row in query.with_entities(Reservation.id).all()]
    if not ids:
        return 0
    # Découpage : SQLite limite le nombre de paramètres d'une requête.
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        ReservationSegment.query.filter(
            ReservationSegment.reservation_id.in_(chunk)
        ).delete(synchronize_session=False)
        Reservation.query.filter(Reservation.id.in_(chunk)).delete(
            synchronize_session=False
        )
    return len(ids)


def find_orphan_segments():
    """Segments dont la réservation ou le véhicule n'existe plus."""

    reservation_ids = db.session.query(Reservation.id).subquery()
    vehicle_ids = db.session.query(Vehicle.id).subquery()
    return (
        ReservationSegment.query.filter(
            or_(
                ReservationSegment.reservation_id.notin_(
                    db.session.query(reservation_ids.c.id)
                ),
                ReservationSegment.vehicle_id.notin_(
                    db.session.query(vehicle_ids.c.id)
                ),
            )
        )
        .order_by(ReservationSegment.start_at)
        .all()
    )


def find_shadowed_segments():
    """Segments d'une réservation qui a aussi un véhicule global.

    Seule l'ancienne validation créait cet état : passer la réservation sur B
    laissait en place les segments posés sur A, qui bloquaient A pour
    personne. Une attribution globale remplace les segments ; ceux qui
    restent sont des résidus.
    """

    return (
        ReservationSegment.query.join(Reservation)
        .filter(Reservation.vehicle_id.isnot(None))
        .order_by(ReservationSegment.start_at)
        .all()
    )


def purge_expired_requests():
    """Archive or delete expired reservations depending on their status.

    * Pending reservations are **deleted** once their ``end_at`` is older than
      two days.
    * Approved/rejected reservations are **archived** (``archived_at`` set) once
      their ``end_at`` is older than seven days so that they disappear from the
      admin listing while remaining available in the monthly calendar.
    """

    now = datetime.utcnow()
    pending_threshold = now - timedelta(days=2)
    final_threshold = now - timedelta(days=7)

    pending_deleted = delete_reservations(
        Reservation.query.filter(
            Reservation.status == "pending",
            Reservation.end_at < pending_threshold,
        )
    )

    archived_count = Reservation.query.filter(
        Reservation.status != "pending",
        Reservation.end_at < final_threshold,
        Reservation.archived_at.is_(None),
    ).update({"archived_at": now}, synchronize_session=False)

    total_processed = (pending_deleted or 0) + (archived_count or 0)
    if total_processed:
        db.session.commit()
    return total_processed


def purge_archived_reservations(max_age_days=180):
    """Permanently delete reservations archived for longer than ``max_age_days``."""

    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    deleted = delete_reservations(
        Reservation.query.filter(
            Reservation.archived_at.isnot(None),
            Reservation.archived_at < cutoff,
        )
    )

    if deleted:
        db.session.commit()
    return deleted


@app.cli.command("purge-expired-requests")
def purge_expired_requests_command():
    """Remove expired reservations older than their respective grace period.

    Usage: ``flask purge-expired-requests``
    """
    deleted = purge_expired_requests()
    print(
        "Processed {} expired reservation(s) (pending deleted >2d, others archived >7d).".format(
            deleted
        )
    )


@app.cli.command("purge-archived-reservations")
def purge_archived_reservations_command():
    """Delete archived reservations older than six months (180 days)."""

    deleted = purge_archived_reservations()
    print(
        "Purged {} archived reservation(s) older than 180 days.".format(
            deleted
        )
    )


@app.cli.command("reset-password")
@click.argument("identifier")
def reset_password_command(identifier):
    """Regenerate the password of a user (by identifiant or e-mail).

    Usage: ``flask reset-password dupontj`` — rescue path for the super
    administrator if the web interface is not reachable.
    """

    user = User.find_by_login(identifier) or User.query.filter_by(
        email=identifier.strip().lower()
    ).first()
    if not user:
        print("Utilisateur introuvable")
        raise SystemExit(1)
    if not user.username:
        user.assign_username()
    password = user.set_random_password()
    db.session.commit()
    print(f"Identifiant  : {user.username}")
    print(f"Mot de passe : {password}")


@app.cli.command("set-username")
@click.argument("email")
@click.argument("username")
def set_username_command(email, username):
    """Change the login identifier of the user owning ``email``."""

    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        print("Utilisateur introuvable")
        raise SystemExit(1)
    candidate = username.strip().lower()
    if User.username_taken(candidate, exclude_id=user.id):
        print(f"L'identifiant '{candidate}' est déjà utilisé")
        raise SystemExit(1)
    user.username = candidate
    db.session.commit()
    print(f"{user.email} -> identifiant '{user.username}'")


@app.cli.command("list-usernames")
def list_usernames_command():
    """Print every account with its login identifier."""

    for user in User.query.order_by(User.username).all():
        print(f"{user.username or '(aucun)':20} {user.email:40} {user.role:10} {user.status}")


def purge_expired_credentials():
    """Effacer les mots de passe en clair dont l'affichage a expiré.

    Appelée avant chaque requête. On lit d'abord : une écriture à chaque page
    prendrait le verrou de SQLite pour rien, alors qu'il n'y a presque jamais
    rien à effacer.
    """

    limite = datetime.utcnow() - timedelta(minutes=CredentialHandoff.MAX_AGE_MINUTES)
    perimee = CredentialHandoff.query.filter(CredentialHandoff.created_at < limite)
    if perimee.first() is None:
        return 0
    nombre = perimee.delete(synchronize_session=False)
    db.session.commit()
    return nombre


def store_credentials(target, password, *, regenerated, mail_sent):
    """Garder les identifiants côté serveur et déposer un jeton en session.

    Le mot de passe en clair ne doit jamais partir dans le cookie de session.
    """

    CredentialHandoff.query.filter(
        CredentialHandoff.created_at
        < datetime.utcnow() - timedelta(minutes=CredentialHandoff.MAX_AGE_MINUTES)
    ).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    db.session.add(
        CredentialHandoff(
            token=token,
            user_id=target.id,
            password=password,
            regenerated=regenerated,
            mail_sent=mail_sent,
        )
    )
    db.session.commit()
    session["credentials_token"] = token


def pop_credentials():
    """Récupérer puis supprimer les identifiants en attente d'affichage."""

    token = session.pop("credentials_token", None)
    if not token:
        return None
    handoff = CredentialHandoff.query.filter_by(token=token).first()
    if handoff is None:
        return None
    expired = handoff.created_at < datetime.utcnow() - timedelta(
        minutes=CredentialHandoff.MAX_AGE_MINUTES
    )
    target = handoff.user
    creds = None
    if not expired and target is not None:
        creds = {
            "user_id": target.id,
            "username": target.username,
            "password": handoff.password,
            "email": target.email,
            "name": f"{target.first_name or ''} {target.last_name or ''}".strip()
            or target.name,
            "regenerated": handoff.regenerated,
            "mail_sent": handoff.mail_sent,
        }
    db.session.delete(handoff)
    db.session.commit()
    return creds


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    user = db.session.get(User, uid)
    if user is None:
        session.clear()
        return None
    # Un mot de passe régénéré doit fermer les sessions déjà ouvertes.
    if session.get("pwd_stamp") != user.session_stamp(app.config["SECRET_KEY"]):
        session.clear()
        return None
    return user


@app.route("/api/users/search", methods=["GET"])
def search_users():
    """Return active users matching the search term.

    The current user is excluded by default unless an administrator requests
    suggestions with the ``include_self`` flag enabled.
    """
    u = current_user()
    if not u or u.status != "active":
        return jsonify([]), 403
    term = (request.args.get("q") or "").strip()
    if not term:
        return jsonify([])
    include_self_param = (request.args.get("include_self") or "").strip().lower()
    include_self_requested = include_self_param in {"1", "true", "yes", "on"}
    can_include_self = include_self_requested and u.role in {
        User.ROLE_ADMIN,
        User.ROLE_SUPERADMIN,
    }
    pattern = f"%{term}%"
    filters = [
        User.status == "active",
        or_(
            User.first_name.ilike(pattern),
            User.last_name.ilike(pattern),
        ),
    ]
    if not can_include_self:
        filters.append(User.id != u.id)
    users = (
        User.query.filter(*filters)
        .order_by(User.first_name.asc(), User.last_name.asc())
        .limit(10)
        .all()
    )
    payload = []
    for user in users:
        first = (user.first_name or "").strip()
        last = (user.last_name or "").strip()
        if first and last:
            label = f"{first} {last}"
        elif first:
            label = first
        elif last:
            label = last
        else:
            label = user.name
        payload.append({
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "label": label.strip(),
        })
    return jsonify(payload)


def role_required(*roles):
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            u = current_user()
            if not u or u.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return decorated
    return wrapper


# simple datetime formatter for templates
@app.template_filter("dt")
def _fmt_dt(v):
    return v.strftime("%d/%m/%Y %H:%M") if v else ""


# French date formatter
JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


@app.template_filter("date_fr")
def _date_fr(v, fmt="full"):
    """Format date in French. fmt: 'full' (Lundi 16 décembre 2024) or 'short' (16/12/2024)"""
    if not v:
        return ""
    if fmt == "short":
        return v.strftime("%d/%m/%Y")
    jour = JOURS_FR[v.weekday()]
    return f"{jour} {v.day} {MOIS_FR[v.month]} {v.year}"


# --- Santé
@app.route("/__ping__", methods=["GET"])
def __ping__():
    return "OK", 200


# --- PWA : service worker servi à la racine pour couvrir tout le site
@app.route("/service-worker.js")
def service_worker():
    resp = send_from_directory(app.static_folder, "service-worker.js")
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.route("/installer")
def install_guide():
    """Guide d'installation sur téléphone (accessible sans connexion)."""

    u = current_user()
    return render_template("install.html", user=u, current_user=u)


# --- Gestion de l'expiration de session
@app.before_request
def _purge_credentials():
    # Les fichiers statiques n'y changent rien : inutile d'interroger la base.
    if request.path.startswith("/static/"):
        return None
    try:
        purge_expired_credentials()
    except Exception:  # noqa: BLE001 - une purge ratée ne bloque pas la page
        db.session.rollback()
        app.logger.exception("Purge des identifiants expires impossible")
    return None


@app.before_request
def _check_session_timeout():
    timeout = app.config.get("SESSION_TIMEOUT_MINUTES")
    if not timeout:
        return None
    uid = session.get("uid")
    if not uid:
        return None
    last_activity = session.get("last_activity")
    if not last_activity:
        session["last_activity"] = datetime.utcnow().isoformat()
        session.permanent = True
        return None
    try:
        last_dt = datetime.fromisoformat(last_activity)
    except (TypeError, ValueError):
        session["last_activity"] = datetime.utcnow().isoformat()
        session.permanent = True
        return None
    if datetime.utcnow() - last_dt > timedelta(minutes=timeout):
        session.pop("uid", None)
        session.pop("last_activity", None)
        flash("Session expirée pour inactivité", "warning")
        return redirect(url_for("login"))
    session["last_activity"] = datetime.utcnow().isoformat()
    session.permanent = True
    return None


# --- Garde: force /login pour les non-connectés (sans boucle)
@app.before_request
def _force_login():
    p = request.path or "/"
    public = {
        "/login",
        "/logout",
        "/__ping__",
        "/home",
        "/",
        "/service-worker.js",
        "/installer",
    }
    if p in public or p.startswith("/static/"):
        return None
    u = current_user() if session.get("uid") else None
    if u is None:
        # Pas de session, ou session close par une régénération de mot de
        # passe ou la suppression du compte : on renvoie vers la connexion.
        nxt = request.full_path if request.query_string else p
        return redirect(
            "/login" + (f"?next={_urlquote(nxt)}" if nxt else "")
        )
    if u.status != "active":
        flash("Compte non activé", "danger")
        return redirect(url_for("home"))
    return None


@app.errorhandler(403)
def forbidden(_):
    return render_template("403.html", user=current_user()), 403


@app.route("/home")
@app.route("/")
def home():
    u = current_user()
    if not u:
        return redirect(url_for("login"))
    if u.role == User.ROLE_SUPERADMIN:
        template = "superadmin_home.html"
    elif u.role == User.ROLE_ADMIN:
        template = "admin_home.html"
    elif u.role == User.ROLE_USER:
        template = "user_home.html"
    else:
        return redirect(url_for("login"))
    if u.status != "active":
        return render_template(template, user=u, current_user=u)
    now = local_now()
    pending_count = 0
    if u.role in (User.ROLE_ADMIN, User.ROLE_SUPERADMIN):
        pending_count = Reservation.query.filter(
            Reservation.status == "pending",
            Reservation.archived_at.is_(None),
        ).count()
    alerte_mail = None
    if u.role in (User.ROLE_ADMIN, User.ROLE_SUPERADMIN):
        # Au plus une fois par semaine, et seulement pour un administrateur :
        # une simple authentification, sans envoi. Aucun minuteur a installer,
        # donc rien a oublier d'activer.
        refresh_mail_health_if_due()
        alerte_mail = mail_alert()
    return render_template(
        template,
        user=u,
        current_user=u,
        now=now,
        overview=today_overview(now),
        my_reservations=my_upcoming_reservations(u, now),
        pending_count=pending_count,
        alerte_mail=alerte_mail,
        slot_label=reservation_slot_label,
        vehicle_codes=reservation_vehicle_codes,
    )


@app.route("/reservation/<int:rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    """Let a user cancel one of their own upcoming reservations."""

    u = current_user()
    r = db.get_or_404(Reservation, rid)
    if r.user_id != u.id:
        abort(403)
    if r.archived_at is not None or r.status not in ("pending", "approved"):
        flash("Cette réservation ne peut plus être annulée.", "warning")
        return redirect(url_for("home"))
    if r.end_at <= local_now():
        flash("Cette réservation est terminée et ne peut plus être annulée.", "warning")
        return redirect(url_for("home"))

    start_str = r.start_at.strftime("%d/%m/%Y %H:%M")
    end_str = r.end_at.strftime("%d/%m/%Y %H:%M")
    codes = reservation_vehicle_codes(r)
    vehicle_info = ", ".join(codes) if codes else "non attribué"
    was_pending = r.status == "pending"
    participants = reservation_notification_recipients(r)

    r.status = "cancelled"
    # Les segments portent l'attribution jour par jour : les supprimer libère
    # immédiatement les véhicules pour d'autres demandes.
    for seg in list(r.segments):
        db.session.delete(seg)
    db.session.commit()

    admin_recipients = _normalize_email_candidates(
        admin_notification_recipients(
            fallback_when_empty=False, include_account_review=False
        )
    )
    if admin_recipients:
        notify(
            "Réservation annulée par l'utilisateur",
            (
                f"{u.name} a annulé sa {'demande de réservation' if was_pending else 'réservation'} "
                f"du {start_str} au {end_str} (véhicule : {vehicle_info}).\n"
                "Aucune action n'est nécessaire : le véhicule est de nouveau disponible."
            ),
            admin_recipients,
        )
    if participants:
        notify(
            "Réservation annulée",
            (
                f"La réservation du {start_str} au {end_str} (véhicule : {vehicle_info}) "
                f"a été annulée par {u.name}."
            ),
            participants,
        )
    flash("Votre réservation a été annulée.", "success")
    return redirect(url_for("home"))


# --- Routes de connexion
def _safe_next_url(candidate):
    """Only allow redirections to a relative path of this application.

    Prevents an attacker from crafting ``/login?next=https://evil.example``
    phishing links.
    """

    if not candidate:
        return None
    candidate = candidate.strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return None
    if "\\" in candidate or ":" in candidate.split("?", 1)[0]:
        return None
    return candidate


def client_ip():
    """Adresse du client, telle que transmise par Caddy.

    ``ProxyFix`` (voir la création de l'application) a déjà remplacé
    ``remote_addr`` par l'adresse que le proxy a vue, et non par celle que le
    client prétend avoir.
    """

    return (request.remote_addr or "")[:45] or None


def _lockout_remaining(failures_query, max_attempts, lockout_minutes, now):
    """Return remaining lock minutes (>=1) if ``failures_query`` exceeds the limit."""

    if max_attempts <= 0:
        return 0
    window_start = now - timedelta(minutes=lockout_minutes)
    recent = (
        failures_query.filter(LoginAttempt.created_at > window_start)
        .order_by(LoginAttempt.created_at.desc())
        .limit(max_attempts)
        .all()
    )
    if len(recent) < max_attempts:
        return 0
    latest = recent[0].created_at
    remaining = (latest + timedelta(minutes=lockout_minutes)) - now
    return max(1, int(remaining.total_seconds() // 60) + 1)


def login_blocked_minutes(identifier, ip, now=None):
    """Minutes before ``identifier`` / ``ip`` may try again, 0 if not blocked."""

    now = now or datetime.utcnow()
    lockout = app.config.get("LOGIN_LOCKOUT_MINUTES", 15)
    blocked = 0
    if identifier:
        blocked = _lockout_remaining(
            LoginAttempt.query.filter(
                LoginAttempt.username == identifier,
                LoginAttempt.success.is_(False),
            ),
            app.config.get("LOGIN_MAX_ATTEMPTS", 5),
            lockout,
            now,
        )
    if ip:
        blocked = max(
            blocked,
            _lockout_remaining(
                LoginAttempt.query.filter(
                    LoginAttempt.ip == ip,
                    LoginAttempt.success.is_(False),
                ),
                app.config.get("LOGIN_IP_MAX_ATTEMPTS", 30),
                lockout,
                now,
            ),
        )
    return blocked


def login_attempts_left(identifier, now=None):
    """Essais restants avant le blocage de l'identifiant, selon la même règle
    que ``login_blocked_minutes``."""

    now = now or datetime.utcnow()
    maximum = app.config.get("LOGIN_MAX_ATTEMPTS", 5)
    if maximum <= 0 or not identifier:
        return None
    debut = now - timedelta(minutes=app.config.get("LOGIN_LOCKOUT_MINUTES", 15))
    echecs = LoginAttempt.query.filter(
        LoginAttempt.username == identifier,
        LoginAttempt.success.is_(False),
        LoginAttempt.created_at > debut,
    ).count()
    return max(0, maximum - echecs)


def password_matches(user, typed):
    """Le mot de passe saisi, tel quel puis sans espaces autour.

    Les mots de passe sont générés par l'application et ne contiennent jamais
    d'espace ; un copier-coller depuis l'e-mail d'identifiants en ajoute
    souvent une en fin de ligne, et chaque échec rapproche du blocage. On
    essaie d'abord la saisie exacte, pour ne jamais refuser un mot de passe
    choisi autrement (celui du superadministrateur initial).
    """

    typed = typed or ""
    if user.check_password(typed):
        return True
    nettoye = typed.strip()
    return nettoye != typed and bool(nettoye) and user.check_password(nettoye)


def record_login_attempt(identifier, ip, success):
    """Store an attempt; a success clears the identifier's failure counter."""

    now = datetime.utcnow()
    db.session.add(
        LoginAttempt(username=identifier or "", ip=ip, success=bool(success), created_at=now)
    )
    if success and identifier:
        LoginAttempt.query.filter(
            LoginAttempt.username == identifier,
            LoginAttempt.success.is_(False),
        ).delete(synchronize_session=False)
    # Historique conservé 30 jours.
    LoginAttempt.query.filter(
        LoginAttempt.created_at < now - timedelta(days=30)
    ).delete(synchronize_session=False)
    db.session.commit()


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        identifier = (form.username.data or "").strip().lower()
        ip = client_ip()
        blocked = login_blocked_minutes(identifier, ip)
        if blocked:
            app.logger.warning("Connexion bloquée pour '%s' depuis %s", identifier, ip)
            flash(
                f"Trop de tentatives échouées. Réessayez dans {blocked} minute{'s' if blocked > 1 else ''}.",
                "danger",
            )
            return render_template("login.html", form=form), 429
        u = User.find_by_login(identifier)
        if u and password_matches(u, form.password.data):
            record_login_attempt(identifier, ip, True)
            session["uid"] = u.id
            session["pwd_stamp"] = u.session_stamp(app.config["SECRET_KEY"])
            session["last_activity"] = datetime.utcnow().isoformat()
            session.permanent = True
            return redirect(
                _safe_next_url(request.args.get("next")) or url_for("home")
            )
        record_login_attempt(identifier, ip, False)
        app.logger.warning("Échec de connexion pour '%s' depuis %s", identifier, ip)
        # Prévenir avant le blocage plutôt que le découvrir : une faute de
        # frappe sur un mot de passe aléatoire est vite arrivée sur téléphone.
        restants = login_attempts_left(identifier)
        duree = app.config.get("LOGIN_LOCKOUT_MINUTES", 15)
        if restants == 0:
            flash(f"Identifiant ou mot de passe incorrect. Connexion bloquée "
                  f"{duree} minutes pour cet identifiant.", "danger")
        elif restants is not None and restants <= 2:
            flash(f"Identifiant ou mot de passe incorrect. Attention : encore "
                  f"{restants} essai{'s' if restants > 1 else ''} avant un blocage "
                  f"de {duree} minutes.", "warning")
        else:
            flash("Identifiant ou mot de passe incorrect.", "danger")
    return render_template("login.html", form=form), 200


@app.cli.command("repair-orphan-segments")
@click.option("--dry-run", is_flag=True, help="Afficher sans rien supprimer")
def repair_orphan_segments_command(dry_run):
    """Supprimer les segments dont la réservation ou le véhicule n'existe plus.

    Ces segments « fantômes » bloquent un véhicule sans apparaître au planning.
    Ils ont pu être créés par les suppressions en masse d'avant ce correctif.
    """

    orphans = find_orphan_segments()
    existing_vehicles = {v.id for v in Vehicle.query.all()}
    dangling = Reservation.query.filter(
        Reservation.vehicle_id.isnot(None),
        Reservation.vehicle_id.notin_(existing_vehicles or [-1]),
    ).all()

    residus = find_shadowed_segments()

    if not orphans and not dangling and not residus:
        print("Aucun segment fantôme. Rien à réparer.")
        return

    for seg in orphans:
        raison = (
            "réservation supprimée"
            if db.session.get(Reservation, seg.reservation_id) is None
            else "véhicule supprimé"
        )
        vehicule = db.session.get(Vehicle, seg.vehicle_id)
        print(
            f"  segment #{seg.id} du {seg.start_at.strftime('%d/%m/%Y')} "
            f"au {seg.end_at.strftime('%d/%m/%Y')} "
            f"({vehicule.code if vehicule else 'véhicule inconnu'}) : {raison}"
        )
    for r in dangling:
        print(f"  réservation #{r.id} pointe vers un véhicule supprimé")
    for seg in residus:
        print(
            f"  segment #{seg.id} du {seg.start_at.strftime('%d/%m/%Y')} "
            f"({seg.vehicle.code}) : reste d'une ancienne attribution de la "
            f"réservation #{seg.reservation_id}, passée depuis sur "
            f"{seg.reservation.vehicle.code}"
        )

    if dry_run:
        print(f"\n{len(orphans) + len(residus)} segment(s) et {len(dangling)} "
              "réservation(s) à corriger (simulation).")
        return

    for seg in orphans + residus:
        db.session.delete(seg)
    for r in dangling:
        r.vehicle_id = None
    db.session.commit()
    print(
        f"\n{len(orphans) + len(residus)} segment(s) fantôme(s) supprimé(s), "
        f"{len(dangling)} réservation(s) détachée(s) d'un véhicule supprimé."
    )


@app.cli.command("check-integrity")
def check_integrity_command():
    """Vérifier la base : fichier sain, aucune référence cassée.

    À lancer avant et après une mise à jour. Les clés étrangères empêchent
    désormais toute nouvelle référence cassée, mais ne corrigent pas celles
    laissées par l'ancien code : cette commande les montre.
    """

    sain = db.session.execute(db.text("PRAGMA integrity_check")).scalar()
    casses = db.session.execute(db.text("PRAGMA foreign_key_check")).fetchall()
    cles = db.session.execute(db.text("PRAGMA foreign_keys")).scalar()

    print(f"Fichier de base : {'sain' if sain == 'ok' else sain}")
    print(f"Clés étrangères : {'actives' if cles else 'désactivées'}")
    if not casses:
        print("Références : aucune référence cassée.")
    else:
        print(f"Références : {len(casses)} référence(s) cassée(s) :")
        for table, ligne, parent, _ in casses:
            print(f"  - {table} n°{ligne} désigne un(e) {parent} qui n'existe plus")
        print("Pour les segments, « flask repair-orphan-segments » les répare.")
    residus = find_shadowed_segments()
    if not residus:
        print("Attributions : aucun segment resté sur un ancien véhicule.")
    else:
        print(f"Attributions : {len(residus)} segment(s) resté(s) sur un ancien "
              "véhicule, qu'ils bloquent pour personne.")
        print("« flask repair-orphan-segments » les retire.")
    if sain != "ok" or casses or residus:
        raise SystemExit(1)


@app.cli.command("check-mail")
@click.option("--force", is_flag=True,
              help="Vérifier même si le dernier contrôle est récent")
def check_mail_command(force):
    """Vérifier que le compte d'envoi des e-mails est toujours accepté.

    L'application fait déjà ce contrôle toute seule, au plus une fois par
    semaine, quand un administrateur ouvre son accueil. Cette commande sert à
    le déclencher à la demande, ou à le planifier.
    """

    manquants = missing_mail_settings()
    if manquants:
        print("Configuration incomplete : il manque " + ", ".join(manquants) + ".")
        raise SystemExit(1)

    etat = refresh_mail_health_if_due(force=True)
    if etat and etat["ok"]:
        print("Envoi des e-mails : compte accepte.")
        return
    detail = (etat or {}).get("detail", "")
    print(f"Envoi des e-mails : REFUSE. {detail}")
    explication = explain_mail_error(detail)
    if explication:
        print(explication)
    raise SystemExit(1)


@app.cli.command("login-attempts")
@click.option("--hours", default=24, show_default=True, help="Période à afficher")
@click.option("--all", "show_all", is_flag=True, help="Inclure les connexions réussies")
def login_attempts_command(hours, show_all):
    """Afficher les tentatives de connexion récentes (échecs par défaut)."""

    since = datetime.utcnow() - timedelta(hours=hours)
    query = LoginAttempt.query.filter(LoginAttempt.created_at > since)
    if not show_all:
        query = query.filter(LoginAttempt.success.is_(False))
    rows = query.order_by(LoginAttempt.created_at.desc()).all()
    if not rows:
        print(f"Aucune tentative {'enregistrée' if show_all else 'échouée'} depuis {hours} h.")
        return
    for a in rows:
        status = "OK    " if a.success else "ÉCHEC "
        print(f"{a.created_at.strftime('%d/%m/%Y %H:%M:%S')} UTC  {status} {a.username:20} {a.ip or '-'}")
    if not show_all:
        counts = {}
        for a in rows:
            counts[a.username] = counts.get(a.username, 0) + 1
        worst = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
        print("\nIdentifiants les plus visés : " + ", ".join(f"{u} ({n})" for u, n in worst))


@app.route("/logout")
def logout():
    session.pop("uid", None)
    session.pop("last_activity", None)
    flash("Déconnecté", "info")
    return redirect(url_for("login"))


def _mail_result_ok(result):
    """Interpréter la valeur renvoyée par l'expéditeur.

    ``send_mail_msmtp`` renvoie ``(True, "sent")`` ou ``(False, "smtp error…")``
    au lieu de lever une exception : un simple ``try/except`` ne voyait donc
    jamais les échecs. On tolère aussi ``None``/``True`` pour les doublures de
    test.
    """

    if result is None or result is True:
        return True, ""
    if isinstance(result, tuple):
        if not result:
            return True, ""
        detail = str(result[1]) if len(result) > 1 else ""
        return bool(result[0]), detail
    return bool(result), ""


# --- santé de l'envoi -------------------------------------------------------
#
# La clé d'application Gmail a été révoquée sans prévenir, et la panne a duré
# jusqu'à ce qu'une création de compte la révèle. L'état de l'envoi est donc
# suivi en continu : chaque envoi réel met l'état à jour, et une vérification
# d'authentification a lieu au plus une fois par semaine.
#
# L'état vit dans un fichier du dossier ``instance``, monté depuis l'hôte : il
# survit aux reconstructions d'image, n'alourdit pas la base ni ses
# sauvegardes, et évite une migration pour une donnée purement technique.

MAIL_HEALTH_FILE = "mail_health.json"
MAIL_CHECK_INTERVAL_DAYS = 7


def _mail_health_path():
    # Surchargeable : sans cela les tests écriraient dans le dossier
    # ``instance`` réel, et un état laissé par un test en ferait échouer un
    # autre selon l'ordre d'exécution.
    return app.config.get("MAIL_HEALTH_PATH") or os.path.join(
        _storage_root, MAIL_HEALTH_FILE
    )


def read_mail_health():
    """Dernier état connu de l'envoi, ou None si rien n'a encore été observé."""

    try:
        with open(_mail_health_path(), encoding="utf-8") as fichier:
            brut = json.load(fichier)
    except (OSError, ValueError):
        return None

    def _date(valeur):
        try:
            return datetime.fromisoformat(valeur) if valeur else None
        except (TypeError, ValueError):
            return None

    return {
        "ok": bool(brut.get("ok")),
        "detail": brut.get("detail") or "",
        "checked_at": _date(brut.get("checked_at")),
        "failing_since": _date(brut.get("failing_since")),
    }


def write_mail_health(ok, detail="", *, checked_at=None):
    """Enregistrer l'état observé, en gardant la date du début de panne."""

    checked_at = checked_at or local_now()
    precedent = read_mail_health()
    if ok:
        failing_since = None
    elif precedent and not precedent["ok"] and precedent["failing_since"]:
        failing_since = precedent["failing_since"]
    else:
        failing_since = checked_at

    donnees = {
        "ok": bool(ok),
        "detail": str(detail or "")[:500],
        "checked_at": checked_at.isoformat(),
        "failing_since": failing_since.isoformat() if failing_since else None,
    }
    chemin = _mail_health_path()
    try:
        # Écriture puis remplacement : plusieurs ouvriers gunicorn peuvent
        # écrire en même temps, on ne veut pas d'un fichier à moitié écrit.
        temporaire = f"{chemin}.{os.getpid()}.tmp"
        with open(temporaire, "w", encoding="utf-8") as fichier:
            json.dump(donnees, fichier)
        os.replace(temporaire, chemin)
    except OSError:
        app.logger.warning("Impossible d'enregistrer l'état de l'envoi des e-mails")
    return donnees


def refresh_mail_health_if_due(force=False):
    """Vérifier l'authentification si le dernier contrôle date de trop.

    Sans cela une clé révoquée passe inaperçue tant que personne n'envoie
    d'e-mail — c'est exactement ce qui s'est produit.
    """

    if missing_mail_settings():
        return read_mail_health()

    etat = read_mail_health()
    if not force and etat and etat["checked_at"]:
        age = local_now() - etat["checked_at"]
        if age < timedelta(days=MAIL_CHECK_INTERVAL_DAYS):
            return etat

    ok, detail = check_mail_login()
    if not ok:
        app.logger.error("Verification de l'envoi des e-mails : %s", detail)
    write_mail_health(ok, detail)
    return read_mail_health()


def mail_alert():
    """Ce qu'il faut afficher aux administrateurs, ou None si tout va bien."""

    manquants = missing_mail_settings()
    if manquants:
        return {"raison": "configuration", "manquants": manquants, "since": None}

    etat = read_mail_health()
    if not etat or etat["ok"]:
        return None
    return {
        "raison": "refus",
        "manquants": [],
        "since": etat["failing_since"],
        "explication": explain_mail_error(etat["detail"]),
    }


def mail_settings_summary():
    """Ce qui est configuré pour l'envoi, sans jamais révéler le mot de passe.

    Destiné à la page de diagnostic : l'administrateur n'a pas accès au
    terminal du Raspberry, et c'est pourtant la première chose à regarder.
    """

    # app.config plutôt que Config : la classe de repli, utilisée si config.py
    # ne s'importe pas, ne porte aucun réglage de messagerie.
    mot_de_passe = app.config.get("MAIL_PASSWORD") or ""
    return {
        "server": app.config.get("MAIL_SERVER") or "",
        "port": app.config.get("MAIL_PORT") or 0,
        "tls": bool(app.config.get("MAIL_USE_TLS")),
        "username": app.config.get("MAIL_USERNAME") or "",
        "sender": (app.config.get("MAIL_DEFAULT_SENDER")
                   or app.config.get("MAIL_USERNAME") or ""),
        # Longueur seulement : une clé d'application Google en fait seize.
        "password_length": len(mot_de_passe),
    }


def missing_mail_settings(summary=None):
    """Réglages absents, en clair. Liste vide si tout est renseigné."""

    summary = summary or mail_settings_summary()
    manquants = []
    if not summary["server"]:
        manquants.append("l'adresse du serveur d'envoi (MAIL_SERVER)")
    if not summary["username"]:
        manquants.append("l'identifiant du compte (MAIL_USERNAME)")
    if not summary["password_length"]:
        manquants.append("la clé d'application (MAIL_PASSWORD)")
    return manquants


# Traductions des pannes d'envoi courantes. L'erreur brute d'un serveur SMTP
# est en anglais et illisible pour qui n'est pas informaticien.
_MAIL_ERROR_HINTS = (
    (("535", "username and password not accepted", "authentication failed",
      "bad credentials", "application-specific password"),
     "Google a refusé l'identifiant ou la clé d'application. Une clé est "
     "invalidée automatiquement quand le mot de passe du compte change ou "
     "quand la double authentification est reconfigurée. Générez-en une "
     "nouvelle dans le compte Google, puis remplacez MAIL_PASSWORD dans le "
     "fichier .env du Raspberry."),
    (("timed out", "timeout", "connection refused", "network is unreachable"),
     "Le serveur d'envoi n'a pas répondu. Le port est probablement bloqué sur "
     "le réseau où se trouve le Raspberry, ou la connexion Internet est "
     "coupée."),
    (("name or service not known", "getaddrinfo", "nodename nor servname"),
     "Le nom du serveur d'envoi est introuvable. Vérifiez MAIL_SERVER dans le "
     "fichier .env : pour Gmail, c'est smtp.gmail.com."),
    # Avant la règle « ssl » ci-dessous, que ce message contient aussi.
    (("certificate verify failed", "certificate_verify_failed"),
     "Le certificat présenté par le serveur d'envoi n'a pas pu être vérifié. "
     "Soit le conteneur n'a pas les certificats racine (paquet "
     "ca-certificates), soit quelqu'un s'intercale entre le Raspberry et "
     "Gmail. Aucun mot de passe n'a été transmis."),
    (("wrong version number", "ssl", "starttls"),
     "Le port et le mode de chiffrement ne s'accordent pas. Pour Gmail : port "
     "587 avec MAIL_USE_TLS=true, ou port 465 avec MAIL_USE_TLS=false."),
    (("sender address rejected", "not allowed", "from address"),
     "Le serveur refuse l'adresse d'expéditeur. Elle doit correspondre au "
     "compte utilisé pour se connecter."),
)


def explain_mail_error(detail):
    """Expliquer une erreur d'envoi en français, ou None si elle est inconnue."""

    texte = (detail or "").lower()
    for motifs, explication in _MAIL_ERROR_HINTS:
        if any(motif in texte for motif in motifs):
            return explication
    return None


def try_mail(recipient):
    """Envoyer un message de test et décrire le résultat.

    Retourne ``(réussi, détail brut, explication en français)``.
    """

    manquants = missing_mail_settings()
    if manquants:
        return False, "", ("Il manque " + ", ".join(manquants) + " dans le "
                           "fichier .env du Raspberry.")
    if not recipient:
        return False, "", ("Votre compte n'a pas d'adresse e-mail : le test "
                           "n'a pas de destinataire.")

    corps = (
        "Ceci est un message de test envoyé depuis l'application de "
        "réservation des véhicules.\n\n"
        "Si vous le recevez, l'envoi des e-mails fonctionne."
    )
    try:
        resultat = send_mail_msmtp("Test d'envoi – Réservation des véhicules",
                                   corps, [recipient])
    except Exception as exc:  # noqa: BLE001 - on veut tous les échecs
        app.logger.exception("Test d'envoi vers %s", recipient)
        write_mail_health(False, str(exc))
        return False, str(exc), explain_mail_error(str(exc))

    envoye, detail = _mail_result_ok(resultat)
    write_mail_health(envoye, detail)
    if envoye:
        return True, detail, None
    app.logger.error("Test d'envoi vers %s : %s", recipient, detail)
    return False, detail, explain_mail_error(detail)


def notify(subject, body, recipients, *, about=""):
    """Envoyer un e-mail en signalant l'échec au lieu de le taire.

    Retourne True si l'envoi a réussi. Un échec est journalisé (repérable avec
    ``docker compose logs vehicules | grep "Echec d'envoi"``) et signalé à
    l'écran à la personne qui a déclenché l'action, car le destinataire, lui,
    ne recevra rien.
    """

    if not recipients:
        return True
    cible = recipients if isinstance(recipients, str) else ", ".join(recipients)
    sujet_log = about or subject
    try:
        resultat = send_mail_msmtp(subject, body, recipients)
    except Exception as exc:  # noqa: BLE001 - on veut tous les échecs
        app.logger.exception("Echec d'envoi (%s) vers %s", sujet_log, cible)
        detail = str(exc)
        envoye = False
    else:
        envoye, detail = _mail_result_ok(resultat)
        if not envoye:
            app.logger.error(
                "Echec d'envoi (%s) vers %s : %s", sujet_log, cible, detail
            )
    # Chaque envoi reel renseigne l'etat : une panne est connue immediatement,
    # sans attendre la verification hebdomadaire.
    write_mail_health(envoye, detail)
    if not envoye and has_request_context():
        flash(
            f"L'e-mail « {subject} » n'a pas pu être envoyé à {cible}. "
            "Prévenez la personne concernée directement.",
            "warning",
        )
    return envoye


def _credentials_email_body(user, password, *, regenerated=False):
    intro = (
        "Votre mot de passe a été régénéré par un administrateur."
        if regenerated
        else "Un compte vient d'être créé pour vous sur la plateforme de réservation des véhicules."
    )
    return (
        "Bonjour,\n\n"
        f"{intro}\n\n"
        f"Identifiant : {user.username}\n"
        f"Mot de passe : {password}\n\n"
        "Ce mot de passe ne peut pas être modifié depuis l'application. "
        "En cas d'oubli, adressez-vous à l'administrateur qui vous en "
        "fournira un nouveau.\n"
    )


def _send_credentials(user, password, *, regenerated=False):
    """E-mail the login details to ``user``; return True if sent."""

    subject = (
        "Nouveau mot de passe – Réservation des véhicules"
        if regenerated
        else "Vos accès – Réservation des véhicules"
    )
    return notify(
        subject,
        _credentials_email_body(user, password, regenerated=regenerated),
        user.email,
        about="envoi des identifiants",
    )


@app.route("/request/new", methods=["GET", "POST"])
def new_request():
    u = current_user()
    if not u or u.status != "active":
        flash("Compte non activé", "danger")
        return redirect(url_for("home"))
    form = NewRequestForm()
    is_admin = u.role in [User.ROLE_ADMIN, User.ROLE_SUPERADMIN]
    if is_admin:
        form.first_name.validators = []
        form.last_name.validators = []
        form.user_lookup.validators = [DataRequired(), Length(max=120)]
        form.user_id.validators = []
        if request.method == "GET":
            full_name = f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip()
            form.user_lookup.data = full_name or u.name or ""
            form.user_id.data = str(u.id)
    else:
        form.user_lookup.validators = []
        form.user_id.validators = []
        # Pré-remplir nom et prénom pour les utilisateurs standards
        if request.method == "GET":
            form.first_name.data = u.first_name or ""
            form.last_name.data = u.last_name or ""
    if form.validate_on_submit():
        target_user = u
        target_user_id = u.id
        if is_admin:
            raw_user_id = (form.user_id.data or "").strip()
            fallback_user = None
            if not raw_user_id:
                lookup_term = (form.user_lookup.data or "").strip()
                if lookup_term:
                    normalized_lookup = lookup_term.lower()
                    include_self = u.role in {
                        User.ROLE_ADMIN,
                        User.ROLE_SUPERADMIN,
                    }

                    def _build_user_label(user_obj):
                        first = (user_obj.first_name or "").strip()
                        last = (user_obj.last_name or "").strip()
                        if first and last:
                            label = f"{first} {last}"
                        elif first:
                            label = first
                        elif last:
                            label = last
                        else:
                            label = user_obj.name or ""
                        return label.strip()

                    pattern = f"%{lookup_term}%"
                    filters = [
                        User.status == "active",
                        or_(
                            User.first_name.ilike(pattern),
                            User.last_name.ilike(pattern),
                        ),
                    ]
                    if not include_self:
                        filters.append(User.id != u.id)
                    candidate_query = (
                        User.query.filter(*filters)
                        .order_by(User.first_name.asc(), User.last_name.asc())
                        .limit(10)
                    )
                    candidates = candidate_query.all()
                    if len(candidates) == 1:
                        fallback_user = candidates[0]
                    else:
                        for candidate in candidates:
                            if (
                                _build_user_label(candidate).lower()
                                == normalized_lookup
                            ):
                                fallback_user = candidate
                                break
                    if not fallback_user:
                        base_query = User.query.filter(User.status == "active")
                        if not include_self:
                            base_query = base_query.filter(User.id != u.id)
                        exact_matches = [
                            candidate
                            for candidate in base_query.all()
                            if _build_user_label(candidate).lower()
                            == normalized_lookup
                        ]
                        if len(exact_matches) == 1:
                            fallback_user = exact_matches[0]
                    if fallback_user:
                        raw_user_id = str(fallback_user.id)
                        form.user_id.data = raw_user_id
            try:
                target_user_id = int(raw_user_id)
            except (TypeError, ValueError):
                form.user_id.errors.append("Sélectionnez un utilisateur valide.")
                flash("Sélectionnez un utilisateur valide.", "danger")
                return render_template("new_request.html", form=form, user=current_user()), 200
            if fallback_user and fallback_user.id == target_user_id:
                target_user = fallback_user
            else:
                target_user = (
                    User.query.filter(
                        User.id == target_user_id,
                        User.status == "active",
                    )
                    .first()
                )
            if not target_user:
                form.user_id.errors.append("Sélectionnez un utilisateur valide.")
                flash("Sélectionnez un utilisateur valide.", "danger")
                return render_template("new_request.html", form=form, user=current_user()), 200
        start_times = {
            "morning": time(8, 0),
            "afternoon": time(13, 0),
            "day": time(8, 0),
        }
        end_times = {
            "morning": time(12, 0),
            "afternoon": time(17, 0),
            "day": time(17, 0),
        }
        # Utiliser la date/slot de début si ceux de fin ne sont pas fournis
        end_date = form.end_date.data or form.start_date.data
        end_slot = form.end_slot.data or form.start_slot.data
        start_at = datetime.combine(
            form.start_date.data, start_times[form.start_slot.data]
        )
        end_at = datetime.combine(
            end_date, end_times[end_slot]
        )
        if end_at <= start_at:
            flash("La date de fin doit être postérieure à la date de début", "danger")
            return render_template("new_request.html", form=form, user=current_user()), 200
        raw_carpool_data = form.carpool_with_ids.data or "[]"
        try:
            carpool_entries = json.loads(raw_carpool_data)
        except json.JSONDecodeError:
            carpool_entries = []
        carpool_ids = []
        carpool_labels = []
        if isinstance(carpool_entries, list):
            for entry in carpool_entries:
                if isinstance(entry, dict):
                    entry_id = entry.get("id")
                    entry_label = entry.get("label")
                    if entry_label:
                        carpool_labels.append(str(entry_label))
                    if entry_id is not None:
                        try:
                            entry_id = int(entry_id)
                        except (TypeError, ValueError):
                            entry_id = None
                    if entry_id is not None:
                        carpool_ids.append(entry_id)
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    entry_id = entry[0]
                    entry_label = entry[1]
                    if entry_label:
                        carpool_labels.append(str(entry_label))
                    try:
                        carpool_ids.append(int(entry_id))
                    except (TypeError, ValueError):
                        continue
                elif isinstance(entry, (int, float)):
                    carpool_ids.append(int(entry))
                elif isinstance(entry, str) and entry:
                    carpool_labels.append(entry)
        normalized_ids = []
        seen_ids = set()
        for entry_id in carpool_ids:
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            normalized_ids.append(entry_id)
        carpool_ids = [cid for cid in normalized_ids if cid != target_user_id]
        carpool_user_details = []
        if carpool_ids:
            carpool_users = (
                User.query.filter(User.id.in_(carpool_ids)).all()
            )
            users_by_id = {usr.id: usr for usr in carpool_users}
            filtered_ids = []
            for cid in carpool_ids:
                user_obj = users_by_id.get(cid)
                if not user_obj:
                    continue
                filtered_ids.append(cid)
                carpool_user_details.append(
                    {
                        "id": user_obj.id,
                        "email": user_obj.email,
                        "name": user_obj.name,
                        "status": user_obj.status,
                    }
                )
            carpool_ids = filtered_ids
        carpool_names = form.carpool_with.data.strip() if form.carpool_with.data else ""
        if not carpool_names and carpool_labels:
            carpool_names = ", ".join(carpool_labels)
        r = Reservation(
            user_id=target_user_id,
            start_at=start_at,
            end_at=end_at,
            purpose=form.purpose.data,
            carpool=form.carpool.data,
            carpool_with=carpool_names or None,
            carpool_with_ids=carpool_ids or None,
            carpool_with_details=carpool_user_details or None,
            notes=form.notes.data,
            status="pending",
        )
        db.session.add(r)
        db.session.commit()
        recipients = admin_notification_recipients(
            fallback_when_empty=False,
            include_account_review=False,
        )
        if not target_user:
            target_user = db.session.get(User, target_user_id)
        recipients = _normalize_email_candidates(recipients)
        if recipients:
            msg = f"Une nouvelle demande a été soumise par {u.name}"
            if target_user and target_user.id != u.id:
                msg += f" pour {target_user.name}"
            msg += "."
            notify(
                "Demande de réservation",
                msg,
                recipients,
                about="alerte des administrateurs",
            )
        if target_user:
            notify(
                "Demande de réservation reçue",
                (
                    f"Nous avons bien reçu votre demande de réservation du "
                    f"{start_at.strftime('%d/%m/%Y %H:%M')} au {end_at.strftime('%d/%m/%Y %H:%M')}. "
                    "Elle est en attente de validation."
                ),
                target_user.email,
            )
        flash("Votre demande a été transmise.", "success")
        return redirect(url_for("home"))
    return render_template("new_request.html", form=form, user=current_user())


@app.route("/contact", methods=["GET", "POST"])
@role_required(User.ROLE_USER, User.ROLE_ADMIN, User.ROLE_SUPERADMIN)
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        recipients = admin_notification_recipients(
            fallback_when_empty=False,
            include_account_review=False,
        )
        recipients = _normalize_email_candidates(recipients)
        if recipients:
            u = current_user()
            # Libellé de l'objet pour l'email
            subject_labels = {
                "question": "Question générale",
                "annulation": "Annuler une réservation",
                "mot_de_passe": "Changer mon mot de passe",
                "probleme": "Signaler un problème",
                "autre": "Autre",
            }
            subject_label = subject_labels.get(form.subject.data, "Contact")
            body_admin = (
                f"Objet : {subject_label}\n\n"
                f"{form.message.data}\n\n"
                f"---\n"
                f"Nom : {u.last_name}\n"
                f"Prénom : {u.first_name}\n"
                f"Email : {u.email}"
            )
            notify(
                f"Contact : {subject_label}",
                body_admin,
                recipients,
            )
        notify(
            "Confirmation de message",
            "Votre message a bien été envoyé à l'Administrateur, vous recevrez prochainement une réponse.",
            current_user().email,
        )
        flash("Votre message a été envoyé.", "success")
        return redirect(url_for("home"))
    return render_template("contact.html", form=form, user=current_user())


@app.route("/admin/users")
@role_required("admin", "superadmin")
def admin_users():
    u = current_user()
    q = request.args.get("q")
    users_query = User.query
    if q:
        users_query = users_query.filter(User.name.ilike(f"%{q}%"))
    users = users_query.order_by(User.name).all()
    return render_template(
        "admin_users.html",
        users=users,
        current_user=u,
        user=u,
        ROLE_ADMIN=User.ROLE_ADMIN,
        ROLE_SUPERADMIN=User.ROLE_SUPERADMIN,
    )


@app.route("/admin/users/new", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def admin_user_new():
    u = current_user()
    form = NewUserForm()
    is_superadmin = u.role == User.ROLE_SUPERADMIN
    if not is_superadmin:
        # Un admin ne peut créer que des comptes "user".
        form.role.choices = [(User.ROLE_USER, "user")]
        form.role.data = User.ROLE_USER
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            form.email.errors.append("Cette adresse e-mail est déjà utilisée.")
            return render_template("user_new.html", form=form, user=u, current_user=u), 200
        first_name = form.first_name.data.strip()
        last_name = form.last_name.data.strip()
        target = User(
            name=f"{last_name} {first_name}",
            first_name=first_name,
            last_name=last_name,
            email=email,
            role=form.role.data if is_superadmin else User.ROLE_USER,
            status="active",
        )
        target.assign_username()
        password = target.set_random_password()
        db.session.add(target)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Impossible de créer ce compte (doublon).", "danger")
            return render_template("user_new.html", form=form, user=u, current_user=u), 200
        sent = _send_credentials(target, password)
        store_credentials(target, password, regenerated=False, mail_sent=sent)
        return redirect(url_for("admin_user_credentials"))
    return render_template("user_new.html", form=form, user=u, current_user=u)


@app.route("/admin/users/credentials")
@role_required("admin", "superadmin")
def admin_user_credentials():
    """Show freshly generated credentials exactly once."""

    creds = pop_credentials()
    if not creds:
        return redirect(url_for("admin_users"))
    u = current_user()
    reponse = make_response(render_template(
        "user_credentials.html", creds=creds, user=u, current_user=u
    ))
    # La page affiche un mot de passe : ni le navigateur ni un intermédiaire ne
    # doivent la garder. Sans cela, le bouton « Précédent » peut la réafficher.
    reponse.headers["Cache-Control"] = "no-store"
    reponse.headers["Pragma"] = "no-cache"
    return reponse


@app.route("/admin/mail-test", methods=["GET", "POST"])
@role_required("superadmin")
def admin_mail_test():
    """Vérifier l'envoi des e-mails depuis l'application elle-même.

    L'administrateur n'a pas toujours accès au terminal du Raspberry — il est
    souvent sur son téléphone. Sans cette page, la seule façon de savoir
    pourquoi un e-mail n'est pas parti était de lire le journal du conteneur.
    """

    u = current_user()
    reglages = mail_settings_summary()
    resultat = None
    if request.method == "POST":
        reussi, detail, explication = try_mail(u.email)
        resultat = {"ok": reussi, "detail": detail, "explication": explication,
                    "destinataire": u.email}
    return render_template(
        "mail_test.html",
        reglages=reglages,
        manquants=missing_mail_settings(reglages),
        resultat=resultat,
        user=u,
        current_user=u,
    )


# --- droits sur les comptes ---------------------------------------------------
#
# Chaque route vérifiait le rôle de celui qui agit, jamais celui du compte visé :
# un administrateur pouvait désactiver le superadministrateur ou changer son
# adresse e-mail, et le dernier superadministrateur pouvait se retirer lui-même
# tout accès. Masquer les boutons ne suffit pas, une requête se fabrique à la
# main : la règle vit ici, et toutes les routes la consultent.

ACCOUNT_ACTIONS = ("edit", "activate", "deactivate", "promote", "demote",
                   "reset_password", "delete")


def _is_last_active_superadmin(target):
    """Le compte visé est-il le seul superadministrateur actif ?"""

    if target.role != User.ROLE_SUPERADMIN or target.status != "active":
        return False
    autres = User.query.filter(
        User.role == User.ROLE_SUPERADMIN,
        User.status == "active",
        User.id != target.id,
    ).count()
    return autres == 0


def account_action_refusal(actor, target, action, new_role=None):
    """Pourquoi ``actor`` ne peut pas faire ``action`` sur ``target``.

    Retourne un message en français, ou None si l'action est permise.
    ``new_role`` sert à la modification d'un compte qui change son rôle.
    """

    if actor is None or target is None:
        return "Action impossible."

    if actor.role == User.ROLE_ADMIN:
        # Un administrateur gère les utilisateurs, pas ses pairs ni ses
        # supérieurs.
        if target.role != User.ROLE_USER:
            return ("Seul le superadministrateur peut agir sur un compte "
                    "administrateur ou superadministrateur.")
        if action not in ("edit", "activate", "deactivate"):
            return "Action réservée au superadministrateur."
        return None

    if actor.role != User.ROLE_SUPERADMIN:
        return "Action réservée aux administrateurs."

    # Superadministrateur : tout, sauf se priver de tout recours.
    dernier = _is_last_active_superadmin(target)
    if action == "deactivate" and dernier:
        return ("C'est le dernier superadministrateur actif : le désactiver "
                "retirerait à tout le monde l'accès à l'administration.")
    if action == "delete" and target.role == User.ROLE_SUPERADMIN:
        return "Impossible de supprimer un superadministrateur."
    if action == "promote" and target.role != User.ROLE_USER:
        # « Promouvoir » fait passer à administrateur : appliqué à un
        # superadministrateur, il le rétrogradait sans le dire.
        return "Seul un utilisateur peut être promu administrateur."
    if action == "demote" and target.role != User.ROLE_ADMIN:
        return "Seul un administrateur peut être rétrogradé."
    if action == "edit" and new_role and new_role != User.ROLE_SUPERADMIN and dernier:
        return ("C'est le dernier superadministrateur actif : il ne peut pas "
                "perdre ce rôle.")
    return None


def can_act_on_account(actor, target, action):
    """Pour les gabarits : afficher seulement les actions permises."""

    return account_action_refusal(actor, target, action) is None


def _refuse_account_action(actor, target, action, new_role=None):
    """Signaler le refus et renvoyer vers la liste, ou None si permis."""

    motif = account_action_refusal(actor, target, action, new_role=new_role)
    if motif is None:
        return None
    app.logger.warning(
        "Action %s refusee : %s sur le compte %s (%s)",
        action, actor.username if actor else "?", target.username, target.role,
    )
    flash(motif, "danger")
    return redirect(url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/edit", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def admin_user_edit(user_id):
    target = db.get_or_404(User, user_id)
    u = current_user()
    refus = _refuse_account_action(u, target, "edit")
    if refus:
        return refus
    form = UserForm(obj=target)
    if form.validate_on_submit():
        nouveau_role = form.role.data if u.role == User.ROLE_SUPERADMIN else None
        refus = _refuse_account_action(u, target, "edit", new_role=nouveau_role)
        if refus:
            return refus
        target.first_name = form.first_name.data
        target.last_name = form.last_name.data
        target.name = f"{form.last_name.data} {form.first_name.data}"
        target.email = form.email.data.lower()
        if nouveau_role:
            target.role = nouveau_role
        db.session.commit()
        flash("Utilisateur mis à jour", "success")
        return redirect(url_for("admin_users"))
    return render_template(
        "user_form.html",
        form=form,
        target=target,
        user=u,
        current_user=u,
    )


@app.route("/admin/promote/<int:user_id>", methods=["POST"])
@role_required("superadmin")
def admin_promote(user_id):
    target = db.get_or_404(User, user_id)
    refus = _refuse_account_action(current_user(), target, "promote")
    if refus:
        return refus
    target.role = User.ROLE_ADMIN
    db.session.commit()
    flash("Utilisateur promu administrateur", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/demote/<int:user_id>", methods=["POST"])
@role_required("superadmin")
def admin_demote(user_id):
    target = db.get_or_404(User, user_id)
    refus = _refuse_account_action(current_user(), target, "demote")
    if refus:
        return refus
    target.role = User.ROLE_USER
    db.session.commit()
    flash("Utilisateur rétrogradé", "info")
    return redirect(url_for("admin_users"))


@app.route("/admin/activate/<int:user_id>", methods=["POST"])
@role_required("admin", "superadmin")
def admin_activate(user_id):
    target = db.get_or_404(User, user_id)
    refus = _refuse_account_action(current_user(), target, "activate")
    if refus:
        return refus
    target.status = "active"
    db.session.commit()
    subject = "Votre compte est activé"
    body = (
        "Votre compte est activé. Vous pouvez désormais accéder à la plateforme "
        "de réservation."
    )
    notify(subject, body, target.email)
    flash("Utilisateur activé", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/deactivate/<int:user_id>", methods=["POST"])
@role_required("admin", "superadmin")
def admin_deactivate(user_id):
    target = db.get_or_404(User, user_id)
    refus = _refuse_account_action(current_user(), target, "deactivate")
    if refus:
        return refus
    target.status = "inactive"
    db.session.commit()
    flash("Utilisateur désactivé", "warning")
    return redirect(url_for("admin_users"))


@app.route("/admin/reset_password/<int:user_id>", methods=["POST"])
@role_required("superadmin")
def admin_reset_password(user_id):
    """Generate a brand new random password for ``user_id``.

    Users can never change their own password: only a super administrator can
    regenerate one, which is then shown once on screen and e-mailed.
    """

    target = db.get_or_404(User, user_id)
    refus = _refuse_account_action(current_user(), target, "reset_password")
    if refus:
        return refus
    if not target.username:
        target.assign_username()
    password = target.set_random_password()
    db.session.commit()
    sent = _send_credentials(target, password, regenerated=True)
    store_credentials(target, password, regenerated=True, mail_sent=sent)
    return redirect(url_for("admin_user_credentials"))


@app.route("/admin/delete/<int:user_id>", methods=["POST"])
@role_required("superadmin")
def admin_user_delete(user_id):
    target = db.get_or_404(User, user_id)
    refus = _refuse_account_action(current_user(), target, "delete")
    if refus:
        return refus
    # Suppression des réservations associées et de leurs segments.
    delete_reservations(Reservation.query.filter_by(user_id=target.id))
    # Deux autres tables le désignent. Sans clés étrangères la suppression
    # laissait ces références pendantes ; avec elles, elle échouerait.
    CredentialHandoff.query.filter_by(user_id=target.id).delete(
        synchronize_session=False
    )
    VehicleUnavailability.query.filter_by(created_by=target.id).update(
        {"created_by": None}, synchronize_session=False
    )
    VehicleLoan.query.filter_by(created_by=target.id).update(
        {"created_by": None}, synchronize_session=False
    )
    db.session.delete(target)
    db.session.commit()
    flash("Utilisateur supprimé", "info")
    return redirect(url_for("admin_users"))


@app.route("/admin/vehicles")
@role_required("admin", "superadmin")
def admin_vehicles():
    user = current_user()
    vehicles = Vehicle.query.order_by(Vehicle.code).all()
    now = local_now()
    return render_template(
        "admin_vehicles.html",
        vehicles=vehicles,
        user=user,
        current_user=user,
        unavailable_now=vehicles_unavailability_map(now, now + timedelta(seconds=1)),
    )


@app.route("/admin/vehicles/<int:vehicle_id>/unavailability", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def admin_vehicle_unavailability(vehicle_id):
    """List and declare unavailability periods for a vehicle."""

    user = current_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)
    form = UnavailabilityForm()
    form.category.choices = list(VehicleUnavailability.CATEGORIES)
    now = local_now()
    if form.validate_on_submit():
        start_at = datetime.combine(form.start_date.data, time.min)
        end_at = None
        if form.end_date.data:
            if form.end_date.data < form.start_date.data:
                form.end_date.errors.append("La date de fin doit être postérieure à la date de début.")
                return _render_vehicle_unavailability(vehicle, form, user, now), 200
            end_at = datetime.combine(form.end_date.data, time.max)
        unav = VehicleUnavailability(
            vehicle_id=vehicle.id,
            start_at=start_at,
            end_at=end_at,
            category=form.category.data,
            details=(form.details.data or "").strip() or None,
            created_by=user.id,
        )
        db.session.add(unav)
        db.session.commit()
        affected = reservations_using_vehicle(vehicle.id, start_at, end_at)
        if affected:
            flash(
                f"Indisponibilité enregistrée. Attention : {len(affected)} réservation(s) validée(s) "
                f"utilisent {vehicle.code} sur cette période, pensez à les réattribuer (liste ci-dessous).",
                "warning",
            )
        else:
            flash("Indisponibilité enregistrée.", "success")
        return redirect(url_for("admin_vehicle_unavailability", vehicle_id=vehicle.id))
    if request.method == "GET":
        form.start_date.data = now.date()
    return _render_vehicle_unavailability(vehicle, form, user, now)


def _render_vehicle_unavailability(vehicle, form, user, now):
    entries = (
        VehicleUnavailability.query.filter_by(vehicle_id=vehicle.id)
        .order_by(VehicleUnavailability.start_at.desc())
        .all()
    )
    current_or_future = [e for e in entries if e.end_at is None or e.end_at >= now]
    past = [e for e in entries if e not in current_or_future][:20]
    affected = {}
    for e in current_or_future:
        rows = reservations_using_vehicle(vehicle.id, max(e.start_at, now), e.end_at)
        if rows:
            affected[e.id] = rows
    return render_template(
        "vehicle_unavailability.html",
        vehicle=vehicle,
        form=form,
        current=current_or_future,
        past=past,
        affected=affected,
        now=now,
        user=user,
        current_user=user,
    )


@app.route("/admin/vehicles/unavailability/<int:unav_id>/delete", methods=["POST"])
@role_required("admin", "superadmin")
def admin_vehicle_unavailability_delete(unav_id):
    unav = db.get_or_404(VehicleUnavailability, unav_id)
    vehicle_id = unav.vehicle_id
    db.session.delete(unav)
    db.session.commit()
    flash("Indisponibilité supprimée : le véhicule peut de nouveau être attribué.", "info")
    return redirect(url_for("admin_vehicle_unavailability", vehicle_id=vehicle_id))


# --- prêts des véhicules à usage réservé -----------------------------------------

def occupations_on_vehicle(vehicle_id, start, end):
    """Réservations en cours qui occupent le véhicule sur la période.

    Retourne des ``(début, fin, réservation)`` : pour un segment, ce sont les
    dates du segment, pas celles de la réservation entière.
    """

    out = []
    directes = Reservation.query.filter(
        Reservation.vehicle_id == vehicle_id,
        Reservation.status.notin_(INACTIVE_STATUSES),
        Reservation.start_at < end,
        Reservation.end_at > start,
    ).all()
    out += [(r.start_at, r.end_at, r) for r in directes]
    segments = ReservationSegment.query.join(Reservation).filter(
        ReservationSegment.vehicle_id == vehicle_id,
        Reservation.status.notin_(INACTIVE_STATUSES),
        ReservationSegment.start_at < end,
        ReservationSegment.end_at > start,
    ).all()
    out += [(s.start_at, s.end_at, s.reservation) for s in segments]
    return sorted(out, key=lambda o: o[0])


def reservations_orphaned_by_loan_removal(loan):
    """Réservations qui ne seraient plus couvertes si l'on retirait ce prêt.

    Un autre prêt peut couvrir la même période : seules les réservations
    réellement laissées sans prêt comptent.
    """

    autres = [p for p in loans_for(loan.vehicle_id, loan.start_at, loan.end_at)
              if p.id != loan.id]
    orphelines = []
    for debut, fin, reservation in occupations_on_vehicle(
            loan.vehicle_id, loan.start_at, loan.end_at):
        if not loans_cover(autres, debut, fin):
            orphelines.append(reservation)
    return orphelines


@app.route("/admin/vehicles/<int:vehicle_id>/loans", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def admin_vehicle_loans(vehicle_id):
    """Prêts d'un véhicule à usage réservé : les enregistrer, les retirer."""

    user = current_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)
    if not vehicle.is_reserved:
        flash(f"{vehicle.code} n'est pas à usage réservé : il est déjà attribuable.", "info")
        return redirect(url_for("admin_vehicles"))
    form = LoanForm()
    now = local_now()
    if form.validate_on_submit():
        if form.end_date.data < form.start_date.data:
            form.end_date.errors.append("La date de fin doit être postérieure à la date de début.")
            return _render_vehicle_loans(vehicle, form, user, now), 200
        start_at = datetime.combine(form.start_date.data, time.min)
        end_at = datetime.combine(form.end_date.data, time.max)
        db.session.add(VehicleLoan(
            vehicle_id=vehicle.id,
            start_at=start_at,
            end_at=end_at,
            reason=(form.reason.data or "").strip() or None,
            created_by=user.id,
        ))
        db.session.commit()
        panne = vehicle_unavailability(vehicle.id, start_at, end_at)
        if panne is not None:
            # Le prêt est enregistré, mais une panne l'emporte toujours.
            flash(
                f"Prêt enregistré. Attention : {vehicle.code} est déclaré indisponible "
                f"sur une partie de cette période ({panne.label}) ; il ne sera pas "
                "attribuable ces jours-là.",
                "warning",
            )
        else:
            flash(f"Prêt enregistré : {vehicle.code} peut être attribué sur cette période.",
                  "success")
        return redirect(url_for("admin_vehicle_loans", vehicle_id=vehicle.id))
    if request.method == "GET":
        form.start_date.data = now.date()
    return _render_vehicle_loans(vehicle, form, user, now)


def _render_vehicle_loans(vehicle, form, user, now):
    prets = (VehicleLoan.query.filter_by(vehicle_id=vehicle.id)
             .order_by(VehicleLoan.start_at.desc()).all())
    a_venir = [p for p in prets if p.end_at >= now]
    passes = [p for p in prets if p.end_at < now][:20]
    utilises = {p.id: [o[2] for o in occupations_on_vehicle(vehicle.id, p.start_at, p.end_at)]
                for p in a_venir}
    return render_template(
        "vehicle_loans.html",
        vehicle=vehicle,
        form=form,
        current=sorted(a_venir, key=lambda p: p.start_at),
        past=passes,
        used=utilises,
        now=now,
        user=user,
        current_user=user,
    )


@app.route("/admin/vehicles/loans/<int:loan_id>/delete", methods=["POST"])
@role_required("admin", "superadmin")
def admin_vehicle_loan_delete(loan_id):
    loan = db.get_or_404(VehicleLoan, loan_id)
    vehicle_id = loan.vehicle_id
    orphelines = reservations_orphaned_by_loan_removal(loan)
    if orphelines:
        # Retirer le prêt laisserait ces réservations sur un véhicule que plus
        # rien n'autorise : on demande de les réattribuer d'abord.
        noms = ", ".join(
            f"{r.start_at.strftime('%d/%m')} ({(r.user.first_name or '')} {(r.user.last_name or '')})".strip()
            for r in orphelines[:5]
        )
        flash(
            f"Impossible de retirer ce prêt : {len(orphelines)} réservation(s) l'utilisent "
            f"— {noms}. Réattribuez-les à un autre véhicule d'abord.",
            "danger",
        )
        return redirect(url_for("admin_vehicle_loans", vehicle_id=vehicle_id))
    db.session.delete(loan)
    db.session.commit()
    flash("Prêt retiré : le véhicule revient à son usage réservé.", "info")
    return redirect(url_for("admin_vehicle_loans", vehicle_id=vehicle_id))


@app.route("/admin/vehicles/new", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def admin_vehicle_new():
    if request.method == "POST":
        v = Vehicle(
            code=request.form["code"].strip(),
            label=request.form["label"].strip(),
            category=request.form.get("category", "").strip() or None,
            reserved_for=request.form.get("reserved_for", "").strip() or None,
        )
        db.session.add(v)
        db.session.commit()
        flash("Véhicule créé", "success")
        return redirect(url_for("admin_vehicles"))
    return render_template(
        "vehicle_form.html", vehicle=None, user=current_user()
    )


@app.route("/admin/vehicles/<int:vehicle_id>/edit", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def admin_vehicle_edit(vehicle_id):
    vehicle = db.get_or_404(Vehicle, vehicle_id)
    if request.method == "POST":
        vehicle.code = request.form["code"].strip()
        vehicle.label = request.form["label"].strip()
        vehicle.category = request.form.get("category", "").strip() or None
        vehicle.reserved_for = request.form.get("reserved_for", "").strip() or None
        db.session.commit()
        flash("Véhicule mis à jour", "success")
        return redirect(url_for("admin_vehicles"))
    return render_template(
        "vehicle_form.html", vehicle=vehicle, user=current_user()
    )


@app.route("/admin/vehicles/<int:vehicle_id>/delete", methods=["POST"])
@role_required("admin", "superadmin")
def admin_vehicle_delete(vehicle_id):
    vehicle = db.get_or_404(Vehicle, vehicle_id)
    # Supprimer un véhicule utilisé laisserait des réservations et des segments
    # pointant dans le vide : on refuse et on oriente vers l'indisponibilité,
    # qui retire le véhicule des attributions sans perdre l'historique.
    used = Reservation.query.filter_by(vehicle_id=vehicle.id).count()
    used += ReservationSegment.query.filter_by(vehicle_id=vehicle.id).count()
    if used:
        flash(
            f"Impossible de supprimer {vehicle.code} : {used} réservation(s) l'utilisent. "
            "Déclarez-le plutôt indisponible pour le retirer des attributions "
            "tout en conservant l'historique.",
            "danger",
        )
        return redirect(url_for("admin_vehicles"))
    db.session.delete(vehicle)
    db.session.commit()
    flash("Véhicule supprimé", "info")
    return redirect(url_for("admin_vehicles"))


def vehicle_unavailability(vehicle_id, start, end):
    """Return the first unavailability of ``vehicle_id`` overlapping [start, end)."""

    return (
        VehicleUnavailability.query.filter(
            VehicleUnavailability.vehicle_id == vehicle_id,
            VehicleUnavailability.start_at < end,
            or_(
                VehicleUnavailability.end_at.is_(None),
                VehicleUnavailability.end_at > start,
            ),
        )
        .order_by(VehicleUnavailability.start_at.asc())
        .first()
    )


# Deux prêts consécutifs — du 12 au 15 puis du 16 au 20 — se touchent à la
# microseconde près (fin de journée incluse, début de la suivante).
_LOAN_JOIN_TOLERANCE = timedelta(seconds=1)


def loans_for(vehicle_id, start, end):
    """Prêts du véhicule qui chevauchent [start, end), du plus ancien au plus récent."""

    return (
        VehicleLoan.query.filter(
            VehicleLoan.vehicle_id == vehicle_id,
            VehicleLoan.start_at < end,
            VehicleLoan.end_at > start,
        )
        .order_by(VehicleLoan.start_at.asc())
        .all()
    )


def loans_cover(loans, start, end):
    """Les prêts couvrent-ils toute la période, sans trou ?

    Un prêt du lundi au mercredi ne suffit pas pour une demande du lundi au
    vendredi ; deux prêts consécutifs, si.
    """

    curseur = start
    for pret in sorted(loans, key=lambda p: p.start_at):
        if pret.start_at > curseur + _LOAN_JOIN_TOLERANCE:
            return False
        curseur = max(curseur, pret.end_at)
        if curseur >= end:
            return True
    return curseur >= end


def reserved_block_reason(vehicle, start, end):
    """Pourquoi un véhicule à usage réservé n'est pas attribuable, ou None.

    Hors prêt, il n'est proposé à aucune demande : son titulaire l'utilise
    sans passer par l'application.
    """

    if vehicle is None or not vehicle.is_reserved:
        return None
    if loans_cover(loans_for(vehicle.id, start, end), start, end):
        return None
    return f"Usage réservé — {vehicle.reserved_for.strip()}"


def vehicles_reserved_map(start, end):
    """``{vehicle_id: motif}`` des véhicules réservés non prêtés sur la période."""

    out = {}
    for v in Vehicle.query.filter(Vehicle.reserved_for.isnot(None)).all():
        motif = reserved_block_reason(v, start, end)
        if motif:
            out[v.id] = motif
    return out


def vehicles_unavailability_map(start, end):
    """Return ``{vehicle_id: unavailability}`` for vehicles blocked on the window."""

    out = {}
    for v in Vehicle.query.order_by(Vehicle.code).all():
        unav = vehicle_unavailability(v.id, start, end)
        if unav is not None:
            out[v.id] = unav
    return out


def has_conflict(vehicle_id, start, end, exclude_reservation_id=None):
    if vehicle_unavailability(vehicle_id, start, end) is not None:
        return True
    # Véhicule à usage réservé hors prêt : pas attribuable.
    if reserved_block_reason(db.session.get(Vehicle, vehicle_id), start, end):
        return True
    # Le segment d'une demande refusée ou annulée ne bloque plus rien : on le
    # garde pour l'historique, mais le véhicule redevient libre. Sans cette
    # jointure, le planning le montrait libre et l'attribution le disait pris.
    q_seg = ReservationSegment.query.join(Reservation).filter(
        ReservationSegment.vehicle_id == vehicle_id,
        Reservation.status.notin_(INACTIVE_STATUSES),
        ReservationSegment.end_at > start,
        ReservationSegment.start_at < end,
    )
    if exclude_reservation_id is not None:
        q_seg = q_seg.filter(
            ReservationSegment.reservation_id != exclude_reservation_id
        )
    if q_seg.first():
        return True
    q_res = Reservation.query.filter(
        Reservation.vehicle_id == vehicle_id,
        Reservation.status.notin_(INACTIVE_STATUSES),
        Reservation.end_at > start,
        Reservation.start_at < end,
    )
    if exclude_reservation_id is not None:
        q_res = q_res.filter(Reservation.id != exclude_reservation_id)
    return q_res.first() is not None


def form_vehicle(field="vehicle_id"):
    """Le véhicule désigné par un formulaire, ou None.

    ``int()`` sur un champ absent levait une erreur 500, et un identifiant
    inexistant produisait un segment pointant dans le vide.
    """

    try:
        vehicle_id = int(request.form.get(field, ""))
    except (TypeError, ValueError):
        return None
    return db.session.get(Vehicle, vehicle_id)


def segment_period_error(reservation, start, end):
    """Pourquoi la période d'un segment est invalide, ou None.

    Un segment dont la fin précédait le début, ou qui débordait de la
    réservation, était accepté tel quel et faussait le planning.
    """

    if start is None or end is None:
        return "Indiquez le début et la fin de la période."
    if start >= end:
        return "La fin doit être après le début."
    if start < reservation.start_at or end > reservation.end_at:
        return (
            "La période doit rester dans celle de la réservation, du "
            f"{reservation.start_at.strftime('%d/%m/%Y %Hh%M')} au "
            f"{reservation.end_at.strftime('%d/%m/%Y %Hh%M')}."
        )
    return None


def _form_datetime(field):
    try:
        return datetime.fromisoformat(request.form.get(field, ""))
    except (TypeError, ValueError):
        return None


def free_period(reservation, start, end):
    """Retirer à la réservation tout véhicule posé sur [start, end).

    Un segment qui déborde de la période est coupé : seuls ses morceaux
    hors période restent. Une attribution globale (``vehicle_id`` de la
    réservation) est d'abord convertie en segment couvrant toute la
    réservation, pour pouvoir en retirer une partie.

    Avant, « un jour » désignait en fait le premier segment qui touchait ce
    jour : sur un segment du 1er au 3, supprimer ou changer le 2 agissait sur
    les trois jours. Et un segment ajouté par-dessus un autre donnait deux
    véhicules en même temps à la même réservation.
    """

    # Une journée entière finit à 23:59:59.999999 : le reste coupé doit
    # reprendre à minuit, sinon il toucherait encore ce jour-là.
    if end.time() == time.max:
        end = datetime.combine(end.date() + timedelta(days=1), time.min)

    if reservation.vehicle_id is not None:
        db.session.add(ReservationSegment(
            reservation_id=reservation.id,
            vehicle_id=reservation.vehicle_id,
            start_at=reservation.start_at,
            end_at=reservation.end_at,
        ))
        reservation.vehicle_id = None
        db.session.flush()

    for seg in ReservationSegment.query.filter(
        ReservationSegment.reservation_id == reservation.id,
        ReservationSegment.end_at > start,
        ReservationSegment.start_at < end,
    ).all():
        for debut, fin in ((seg.start_at, start), (end, seg.end_at)):
            for morceau in _day_pieces(debut, fin):
                db.session.add(ReservationSegment(
                    reservation_id=reservation.id,
                    vehicle_id=seg.vehicle_id,
                    start_at=morceau[0],
                    end_at=morceau[1],
                ))
        db.session.delete(seg)
    db.session.flush()


def _day_pieces(debut, fin):
    """[debut, fin) découpé jour par jour, chaque jour finissant à 23:59:59.

    Un segment par jour, comme ceux que crée l'attribution jour par jour :
    chaque jour du planning mène à son propre segment, qu'on peut modifier
    sans toucher aux voisins.
    """

    jour = debut.date()
    while debut < fin:
        fin_du_jour = datetime.combine(jour, time.max)
        morceau_fin = min(fin, fin_du_jour)
        if debut < morceau_fin:
            yield debut, morceau_fin
        jour += timedelta(days=1)
        debut = datetime.combine(jour, time.min)


def assign_whole_reservation(reservation, vehicle_id):
    """Attribuer un véhicule à toute la réservation.

    Les segments posés auparavant sont retirés : ils continuaient de bloquer
    l'ancien véhicule alors que la réservation était passée sur un autre.
    """

    ReservationSegment.query.filter_by(reservation_id=reservation.id).delete(
        synchronize_session="fetch"
    )
    reservation.vehicle_id = vehicle_id


def commit_if_still_free(vehicle_id, start, end, reservation_id):
    """Enregistrer l'attribution en cours, sauf si le véhicule vient d'être pris.

    Entre la vérification de disponibilité et l'enregistrement, un autre
    administrateur peut avoir attribué le même véhicule sur la même période.
    On force l'écriture (``flush`` : SQLite prend alors son verrou d'écriture),
    on revérifie dans la même transaction, et on annule si un conflit est
    apparu entre-temps. Retourne True si l'attribution est enregistrée.
    """

    db.session.flush()
    if has_conflict(vehicle_id, start, end, exclude_reservation_id=reservation_id):
        db.session.rollback()
        return False
    db.session.commit()
    return True


def vehicles_availability(start, end, exclude_reservation_id=None):
    """Chaque véhicule et sa disponibilité sur la période.

    ``exclude_reservation_id`` : la réservation qu'on est en train de gérer ne
    doit pas se bloquer elle-même. Sans cela son propre véhicule apparaissait
    « Occupé », coché mais désactivé — donc jamais envoyé par le formulaire.
    """

    out = []
    for v in Vehicle.query.order_by(Vehicle.code).all():
        conflict = has_conflict(v.id, start, end,
                                exclude_reservation_id=exclude_reservation_id)
        out.append((v, not conflict))
    return out


def local_now():
    """Return the current local (naive) datetime.

    Reservation slots are stored as naive local times (8h-12h, 13h-17h), so
    "now" must be expressed in the same time zone whatever the container's
    system clock is set to (Docker images default to UTC).
    """

    tz_name = app.config.get("APP_TIMEZONE") or "Europe/Paris"
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:
        return datetime.now()


_SLOT_LETTERS = {"Matin": "M", "Après-midi": "A", "Journée": "J"}


def _period_label(start, end):
    """« le 03/09/2026 », « du 03/09 au 05/09 » ou « jusqu'à nouvel ordre »."""

    if end is None:
        return f"depuis le {start.strftime('%d/%m/%Y')}, jusqu'à nouvel ordre"
    if start.date() == end.date():
        return f"le {start.strftime('%d/%m/%Y')}"
    return f"du {start.strftime('%d/%m/%Y')} au {end.strftime('%d/%m/%Y')}"


def _display_name(user):
    """« Prénom Nom », ou le nom enregistré si l'un des deux manque."""

    if user is None:
        return ""
    parties = [p for p in (user.first_name, user.last_name) if p]
    return " ".join(parties) if parties else (user.name or "")


def _source(kind, objet):
    """Identité d'une occupation, pour regrouper ses jours consécutifs.

    ``id`` vaut None tant que l'objet n'est pas enregistré : deux réservations
    distinctes partageraient alors la même clé et seraient fondues en une.
    """

    return (kind, objet.id if objet.id is not None else id(objet))


def calendar_entries(grid):
    """Une ligne par occupation continue, pour la liste détaillée du PDF.

    Dans la grille imprimée, une case ne porte qu'une pastille : le nom et le
    motif y tenaient sur quatre ou cinq lignes, ce qui rendait les lignes si
    hautes qu'une page finissait par les couper en deux. Le détail est donc
    repris dessous, sous forme de liste.

    Elle est construite à partir de la grille, donc à partir de la même source
    de vérité que les cases : une réservation dont seuls certains jours ont été
    réattribués à un autre véhicule apparaît correctement des deux côtés, ce
    qu'un parcours séparé des réservations et des segments manquait.
    """

    presence = {}
    for jour in grid["days"]:
        for vehicle_id, cases in grid["cells"].items():
            for element in cases[jour["key"]]:
                if element["kind"] != "res":
                    continue  # indisponibilités et usage réservé : tableaux à part
                cle = (vehicle_id, element["source"])
                suivi = presence.setdefault(cle, {"item": element, "jours": []})
                suivi["jours"].append(jour["date"])

    lignes = []
    for suivi in presence.values():
        element, jours = suivi["item"], suivi["jours"]
        debut = jours[0]
        for courant, suivant in zip(jours, jours[1:] + [None]):
            # Une interruption d'au moins un jour ferme la periode en cours.
            if suivant is None or (suivant - courant).days > 1:
                lignes.append(
                    {
                        "vehicle": element["vehicle"],
                        "start": debut,
                        "end": courant,
                        "name": element["full_name"] or element["name"],
                        "slot": element["slot"] if debut == courant else "",
                        "purpose": (element["purpose"] or "").strip(),
                    }
                )
                debut = suivant

    lignes.sort(key=lambda l: (l["start"], l["vehicle"]))
    return lignes


def calendar_grid(vehicles, reservations, segments, unavailabilities, start, end, user,
                  loans=None):
    """Pré-calculer le contenu de chaque case du planning.

    Les boucles imbriquées vivaient dans le gabarit et étaient recopiées pour
    la vue mois puis pour la liste mobile ; une troisième vue (semaine) en
    aurait fait une de plus. Le calcul est donc fait une seule fois ici, et
    les gabarits se contentent d'afficher.

    Retourne ``{"days": [...], "cells": {vehicle_id: {"2026-09-21": [item]}}}``
    où chaque *item* porte de quoi remplir la case **et** la fenêtre de détail.
    """

    est_admin = bool(user) and user.role in ("admin", "superadmin")
    unavailabilities = unavailabilities or []
    aujourdhui = local_now().date()

    days = []
    for i in range((end - start).days):
        moment = start + timedelta(days=i)
        days.append(
            {
                "date": moment,
                "key": moment.date().isoformat(),
                "today": moment.date() == aujourdhui,
                "weekend": moment.weekday() >= 5,
            }
        )

    cells = {v.id: {j["key"]: [] for j in days} for v in vehicles}

    def ajouter(vehicle_id, jour, item):
        case = cells.get(vehicle_id)
        if case is not None:
            case[jour["key"]].append(item)

    def item(kind, *, vehicle, name, slot, purpose, period, url, full_name="", source=None):
        return {
            "kind": kind,
            # De quelle occupation vient cette case : permet de regrouper les
            # jours consecutifs sans refaire le raisonnement des segments.
            "source": source,
            "vehicle": vehicle.code,
            "name": name,
            # Le PDF imprime « Prénom Nom », l'écran l'identifiant « Nom Prénom » :
            # les deux formes voyagent ensemble plutôt que d'être recalculées.
            "full_name": full_name or name,
            "slot": slot,
            "letter": {"unav": "I", "reserved": "R"}.get(kind) or _SLOT_LETTERS.get(slot, "J"),
            "purpose": purpose or "",
            "period": period,
            "url": url,
        }

    par_vehicule = {v.id: v for v in vehicles}

    for un in unavailabilities:
        vehicle = par_vehicule.get(un.vehicle_id)
        if vehicle is None:
            continue
        for jour in days:
            d = jour["date"].date()
            if d < un.start_at.date():
                continue
            if un.end_at is not None and d > un.end_at.date():
                continue
            # Une seule pastille « indisponible » par case, même si deux
            # périodes se chevauchent : la case ne fait que quelques pixels.
            if any(x["kind"] == "unav" for x in cells[vehicle.id][jour["key"]]):
                continue
            ajouter(
                vehicle.id,
                jour,
                item(
                    "unav",
                    vehicle=vehicle,
                    name=un.label,
                    slot="Indisponible",
                    purpose="",
                    period=_period_label(un.start_at, un.end_at),
                    source=_source("unav", un),
                    url=url_for("admin_vehicle_unavailability", vehicle_id=vehicle.id)
                    if est_admin
                    else None,
                ),
            )

    # Véhicules à usage réservé : chaque jour hors prêt porte une pastille « R ».
    # Ils étaient déclarés indisponibles comme une panne ; le planning les
    # distingue désormais. Une panne l'emporte : pas de « R » un jour « I ».
    prets = loans or []
    for vehicle in vehicles:
        if not vehicle.is_reserved:
            continue
        siens = [p for p in prets if p.vehicle_id == vehicle.id]
        for jour in days:
            d = jour["date"].date()
            if any(p.start_at.date() <= d <= p.end_at.date() for p in siens):
                continue
            if any(x["kind"] == "unav" for x in cells[vehicle.id][jour["key"]]):
                continue
            ajouter(
                vehicle.id,
                jour,
                item(
                    "reserved",
                    vehicle=vehicle,
                    name=vehicle.reserved_for.strip(),
                    slot="Usage réservé",
                    purpose="",
                    period="Hors période de prêt",
                    url=url_for("admin_vehicle_loans", vehicle_id=vehicle.id)
                    if est_admin
                    else None,
                    source=("reserved", vehicle.id),
                ),
            )

    # Un jour couvert par un segment appartient au segment, pas à la
    # réservation d'origine : sans cela la case afficherait les deux.
    couverts = set()
    for s in segments:
        jour = s.start_at.date()
        while jour <= s.end_at.date():
            couverts.add((s.reservation_id, jour))
            jour += timedelta(days=1)

    for r in reservations:
        vehicle = par_vehicule.get(r.vehicle_id)
        if vehicle is None:
            continue
        for jour in days:
            d = jour["date"].date()
            if not (r.start_at.date() <= d <= r.end_at.date()):
                continue
            if (r.id, d) in couverts:
                continue
            ajouter(
                vehicle.id,
                jour,
                item(
                    "res",
                    vehicle=vehicle,
                    name=r.user.name if r.user else "",
                    full_name=_display_name(r.user),
                    slot=reservation_slot_label(r, jour["date"]),
                    purpose=r.purpose,
                    period=_period_label(r.start_at, r.end_at),
                    source=_source("res", r),
                    url=url_for("manage_request", rid=r.id, day=jour["key"])
                    if est_admin
                    else None,
                ),
            )

    for s in segments:
        vehicle = par_vehicule.get(s.vehicle_id)
        if vehicle is None:
            continue
        r = s.reservation
        for jour in days:
            d = jour["date"].date()
            if not (s.start_at.date() <= d <= s.end_at.date()):
                continue
            ajouter(
                vehicle.id,
                jour,
                item(
                    "res",
                    vehicle=vehicle,
                    name=r.user.name if r and r.user else "",
                    full_name=_display_name(r.user if r else None),
                    slot=reservation_slot_label(s, jour["date"]),
                    purpose=r.purpose if r else "",
                    period=_period_label(s.start_at, s.end_at),
                    source=_source("seg", s),
                    url=url_for("manage_segment", sid=s.id) if est_admin else None,
                ),
            )

    return {"days": days, "cells": cells}


def today_overview(now=None):
    """Return, for each vehicle, its situation at ``now``.

    Each entry is a dict with:

    * ``vehicle``  – the Vehicle
    * ``state``    – ``"out"`` (currently used), ``"later"`` (booked later
                     today) or ``"free"`` (nothing else today)
    * ``current``  – the occupation in progress, if any
    * ``next``     – the next occupation later today, if any
    * ``items``    – every occupation touching today, sorted by start

    An occupation is a dict ``{start, end, reservation}`` built from approved
    reservations (direct vehicle assignment) and from their segments (per-day
    vehicle assignment).
    """

    now = now or local_now()
    day_start = datetime.combine(now.date(), time.min)
    day_end = datetime.combine(now.date(), time.max)
    vehicles = Vehicle.query.order_by(Vehicle.code).all()
    occupations = {v.id: [] for v in vehicles}

    direct = Reservation.query.filter(
        Reservation.status == "approved",
        Reservation.vehicle_id.isnot(None),
        Reservation.start_at <= day_end,
        Reservation.end_at >= day_start,
    ).all()
    for r in direct:
        if r.vehicle_id in occupations:
            occupations[r.vehicle_id].append(
                {"start": r.start_at, "end": r.end_at, "reservation": r}
            )
    segments = (
        ReservationSegment.query.join(Reservation)
        .filter(
            Reservation.status == "approved",
            ReservationSegment.start_at <= day_end,
            ReservationSegment.end_at >= day_start,
        )
        .all()
    )
    for seg in segments:
        if seg.vehicle_id in occupations:
            occupations[seg.vehicle_id].append(
                {"start": seg.start_at, "end": seg.end_at, "reservation": seg.reservation}
            )

    overview = []
    for v in vehicles:
        items = sorted(occupations[v.id], key=lambda it: it["start"])
        current = next(
            (it for it in items if it["start"] <= now < it["end"]), None
        )
        upcoming = [it for it in items if it["start"] > now]
        unav = vehicle_unavailability(v.id, now, now + timedelta(seconds=1))
        # Véhicule du chef ou de l'adjoint : « Libre » induirait en erreur hors
        # prêt, puisqu'aucune demande ne peut l'obtenir.
        pret = None
        if v.is_reserved:
            pret = next(iter(loans_for(v.id, now, now + timedelta(seconds=1))), None)
        if unav is not None:
            state = "unavailable"
        elif current:
            state = "out"
        elif v.is_reserved and pret is None:
            state = "reserved"
        elif upcoming:
            state = "later"
        else:
            state = "free"
        overview.append(
            {
                "vehicle": v,
                "state": state,
                "current": current,
                "next": upcoming[0] if upcoming else None,
                "items": items,
                "unavailability": unav,
                "loan": pret,
            }
        )
    return overview


def reservations_using_vehicle(vehicle_id, start, end):
    """Approved reservations (direct or via segments) using a vehicle on a window."""

    if end is None:
        end = datetime.max
    found = {}
    direct = Reservation.query.filter(
        Reservation.vehicle_id == vehicle_id,
        Reservation.status == "approved",
        Reservation.start_at < end,
        Reservation.end_at > start,
    ).all()
    for r in direct:
        found[r.id] = r
    segs = (
        ReservationSegment.query.join(Reservation)
        .filter(
            ReservationSegment.vehicle_id == vehicle_id,
            Reservation.status == "approved",
            ReservationSegment.start_at < end,
            ReservationSegment.end_at > start,
        )
        .all()
    )
    for seg in segs:
        found[seg.reservation_id] = seg.reservation
    return sorted(found.values(), key=lambda r: r.start_at)


def my_upcoming_reservations(user, now=None):
    """Return the user's pending/approved reservations not finished yet."""

    now = now or local_now()
    return (
        Reservation.query.filter(
            Reservation.user_id == user.id,
            Reservation.archived_at.is_(None),
            Reservation.status.in_(["pending", "approved"]),
            Reservation.end_at > now,
        )
        .order_by(Reservation.start_at.asc())
        .all()
    )


def reservation_vehicle_codes(reservation):
    """Return the vehicle codes attached to a reservation (direct or segments)."""

    codes = []
    if reservation.vehicle is not None:
        codes.append(reservation.vehicle.code)
    for seg in sorted(reservation.segments, key=lambda s: s.start_at):
        if seg.vehicle is not None and seg.vehicle.code not in codes:
            codes.append(seg.vehicle.code)
    return codes


def reservation_carpool_users(reservation):
    """Return active carpoolers associated with a reservation."""

    candidate_ids = []
    details = reservation.carpool_with_details or []
    if isinstance(details, list):
        for entry in details:
            if not isinstance(entry, dict):
                continue
            try:
                entry_id = int(entry.get("id"))
            except (TypeError, ValueError):
                continue
            if entry_id not in candidate_ids:
                candidate_ids.append(entry_id)
    ids_from_field = reservation.carpool_with_ids or []
    if isinstance(ids_from_field, list):
        for entry in ids_from_field:
            try:
                entry_id = int(entry)
            except (TypeError, ValueError):
                continue
            if entry_id not in candidate_ids:
                candidate_ids.append(entry_id)
    if not candidate_ids:
        return []
    users = (
        User.query.filter(
            User.id.in_(candidate_ids),
            User.status == "active",
        ).all()
    )
    user_map = {user.id: user for user in users}
    ordered = [user_map[uid] for uid in candidate_ids if uid in user_map]
    return ordered


def reservation_notification_recipients(reservation):
    """Return unique active recipient emails for reservation notifications."""

    recipients = []
    seen = set()

    def _normalize_email(value):
        if not value:
            return ""
        cleaned = value.strip().strip(",;")
        if cleaned.startswith("<") and cleaned.endswith(">"):
            cleaned = cleaned[1:-1].strip()
        return cleaned.lower()

    def _add_email(email, *, use_normalized_value=False):
        normalized = _normalize_email(email)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        if use_normalized_value or not email:
            recipients.append(normalized)
        else:
            recipients.append(email.strip())

    main_user = reservation.user
    if main_user and main_user.status == "active" and main_user.email:
        _add_email(main_user.email)
    for carpooler in reservation_carpool_users(reservation):
        email = carpooler.email
        _add_email(email)
    if reservation.carpool_with:
        for token in re.split(r"[;,\s]+", reservation.carpool_with):
            if "@" not in token:
                continue
            _add_email(token, use_normalized_value=True)
    return recipients


@app.route("/admin/reservations")
@role_required("admin", "superadmin")
def admin_reservations():
    user = current_user()
    res = (
        Reservation.query.filter(Reservation.archived_at.is_(None))
        .order_by(
            case((Reservation.status == "pending", 0), else_=1),
            case((Reservation.status == "pending", Reservation.created_at), else_=None).asc(),
            Reservation.start_at.desc(),
        )
        .limit(200)
        .all()
    )
    return render_template(
        "admin_reservations.html",
        reservations=res,
        user=user,
        current_user=user,
        slot_label=reservation_slot_label,
    )


@app.route("/admin/leaves", methods=["GET", "POST"])
@role_required("superadmin")
def admin_leaves():
    user = current_user()
    settings = NotificationSettings.query.first()
    if not settings:
        settings = NotificationSettings()
        db.session.add(settings)
        db.session.commit()
    form = NotificationSettingsForm()
    admins = User.query.filter(
        User.role.in_([User.ROLE_SUPERADMIN, User.ROLE_ADMIN])
    ).order_by(User.first_name).all()
    form.recipients.choices = [
        (str(u.id), f"{u.first_name} {u.last_name}") for u in admins
    ]
    if request.method == "GET":
        form.recipients.data = [
            str(uid) for uid in (settings.notify_user_ids or [])
        ]
    if form.validate_on_submit():
        settings.notify_user_ids = [int(uid) for uid in form.recipients.data]
        db.session.commit()
        flash("Préférences enregistrées", "success")
        return redirect(url_for("admin_leaves"))
    return render_template(
        "admin_leaves.html",
        form=form,
        user=user,
        current_user=user,
    )


@app.route("/admin/manage/<int:rid>", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def manage_request(rid):
    r = db.get_or_404(Reservation, rid)
    day_str = request.args.get("day")
    day = None
    if day_str:
        # Un jour mal formé levait une erreur 500 ; un jour hors de la
        # réservation fabriquait un segment dont la fin précédait le début.
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d")
        except ValueError:
            day = None
        if day is None or not (r.start_at.date() <= day.date() <= r.end_at.date()):
            flash("Ce jour ne fait pas partie de la réservation.", "warning")
            return redirect(url_for("manage_request", rid=r.id))
        label = reservation_slot_label(r, day)
        if label == "Matin":
            day_start = datetime.combine(day.date(), time(8, 0))
            day_end = datetime.combine(day.date(), time(12, 0))
        elif label == "Après-midi":
            day_start = datetime.combine(day.date(), time(13, 0))
            day_end = datetime.combine(day.date(), time(17, 0))
        else:
            day_start = datetime.combine(day.date(), time.min)
            day_end = datetime.combine(day.date(), time.max)
        if day_start < r.start_at:
            day_start = r.start_at
        if day_end > r.end_at:
            day_end = r.end_at
    else:
        day_start = r.start_at
        day_end = r.end_at
    if request.method == "POST":
        action = request.form.get("action")
        if action == "segment_day" and day:
            vehicule = form_vehicle()
            if vehicule is None:
                flash("Choisissez un véhicule existant.", "danger")
                return redirect(url_for("manage_request", rid=r.id, day=day_str))
            veh_id = vehicule.id
            if has_conflict(
                veh_id, day_start, day_end, exclude_reservation_id=r.id
            ):
                flash("Conflit détecté lors de la création du segment.", "danger")
            else:
                # Seul ce jour change de véhicule : le reste de la
                # réservation garde le sien.
                free_period(r, day_start, day_end)
                db.session.add(ReservationSegment(
                    reservation_id=r.id,
                    vehicle_id=veh_id,
                    start_at=day_start,
                    end_at=day_end,
                ))
                r.status = "approved"
                if not commit_if_still_free(veh_id, day_start, day_end, r.id):
                    flash(
                        "Ce véhicule vient d'être attribué par un autre "
                        "administrateur. Choisissez-en un autre.",
                        "danger",
                    )
                    return redirect(url_for("admin_reservations"))
                recipients = reservation_notification_recipients(r)
                if recipients:
                    notify(
                        "Véhicule attribué",
                        (
                            f"Véhicule attribué pour votre réservation :\n\n"
                            f"Période : du {day_start.strftime('%d/%m/%Y')} au {day_end.strftime('%d/%m/%Y')}\n"
                            f"Véhicule : {vehicule.code}"
                            + (f" ({vehicule.label})" if vehicule.label else "")
                        ),
                        recipients,
                    )
                flash("Véhicule attribué pour ce jour.", "success")
                return redirect(url_for("admin_reservations"))
        elif action == "delete_day" and day:
            # Retire le véhicule de ce jour seulement, sans toucher aux autres.
            free_period(r, day_start, day_end)
            db.session.commit()
            flash("Véhicule retiré pour ce jour.", "info")
            return redirect(url_for("admin_reservations"))
        if action == "approve":
            # Même garde que les autres chemins d'attribution : un champ
            # absent levait une erreur 500 (oubli du correctif précédent).
            v = form_vehicle()
            if v is None:
                flash("Choisissez un véhicule existant.", "danger")
                return redirect(url_for("manage_request", rid=r.id))
            veh_id = v.id
            reserve = reserved_block_reason(v, r.start_at, r.end_at)
            if reserve:
                flash(f"{v.code} : {reserve}, hors période de prêt. "
                      "Enregistrez d'abord un prêt dans la gestion du parc.",
                      "danger")
            elif has_conflict(v.id, r.start_at, r.end_at, exclude_reservation_id=r.id):
                flash(
                    "Conflit détecté sur ce véhicule pour la période.", "danger"
                )
            else:
                assign_whole_reservation(r, v.id)
                r.status = "approved"
                if not commit_if_still_free(v.id, r.start_at, r.end_at, r.id):
                    flash(
                        "Ce véhicule vient d'être attribué par un autre "
                        "administrateur. Choisissez-en un autre.",
                        "danger",
                    )
                else:
                    recipients = reservation_notification_recipients(r)
                    if recipients:
                        notify(
                            "Véhicule attribué",
                            (
                                f"Véhicule attribué pour votre réservation :\n\n"
                                f"Période : du {r.start_at.strftime('%d/%m/%Y')} au {r.end_at.strftime('%d/%m/%Y')}\n"
                                f"Véhicule : {v.code}"
                                + (f" ({v.label})" if v.label else "")
                            ),
                            recipients,
                        )
                    flash("Demande approuvée et véhicule attribué.", "success")
                    return redirect(url_for("admin_reservations"))
        elif action == "segment":
            start_at = _form_datetime("start_at")
            end_at = _form_datetime("end_at")
            vehicule = form_vehicle()
            erreur = segment_period_error(r, start_at, end_at)
            if erreur is None and vehicule is None:
                erreur = "Choisissez un véhicule existant."
            if erreur:
                # Refusé avant toute écriture.
                flash(erreur, "danger")
                return redirect(url_for("manage_request", rid=r.id))
            veh_id = vehicule.id
            if has_conflict(veh_id, start_at, end_at, exclude_reservation_id=r.id):
                flash("Conflit détecté lors de la création du segment.", "danger")
            else:
                # Le nouveau véhicule remplace celui déjà posé sur la période :
                # jamais deux véhicules en même temps pour une réservation.
                free_period(r, start_at, end_at)
                db.session.add(ReservationSegment(
                    reservation_id=r.id,
                    vehicle_id=veh_id,
                    start_at=start_at,
                    end_at=end_at,
                ))
                r.status = "approved"
                if not commit_if_still_free(veh_id, start_at, end_at, r.id):
                    flash(
                        "Ce véhicule vient d'être attribué par un autre "
                        "administrateur. Choisissez-en un autre.",
                        "danger",
                    )
                    return redirect(url_for("admin_reservations"))
                vehicle = db.session.get(Vehicle, veh_id)
                recipients = reservation_notification_recipients(r)
                if recipients:
                    notify(
                        "Véhicule attribué",
                        (
                            f"Véhicule attribué pour votre réservation :\n\n"
                            f"Période : du {start_at.strftime('%d/%m/%Y')} au {end_at.strftime('%d/%m/%Y')}\n"
                            f"Véhicule : {vehicle.code}"
                            + (f" ({vehicle.label})" if vehicle.label else "")
                        ),
                        recipients,
                    )
                flash("Segment ajouté.", "success")
                return redirect(url_for("admin_reservations"))
        elif action == "reject":
            r.status = "rejected"
            db.session.commit()
            recipients = reservation_notification_recipients(r)
            if recipients:
                notify(
                    "Demande de réservation refusée",
                    (
                        f"Votre demande de réservation du {r.start_at.strftime('%d/%m/%Y %H:%M')} au "
                        f"{r.end_at.strftime('%d/%m/%Y %H:%M')} a été refusée.\n"
                        "Veuillez contacter l'administrateur pour plus d'informations."
                    ),
                    recipients,
                )
            flash("Demande refusée.", "warning")
            return redirect(url_for("admin_reservations"))
        elif action == "delete":
            # Capturer les infos avant suppression
            start_str = r.start_at.strftime('%d/%m/%Y %H:%M')
            end_str = r.end_at.strftime('%d/%m/%Y %H:%M')
            vehicle_info = r.vehicle.code if r.vehicle else "Non attribué"
            recipients = reservation_notification_recipients(r)
            db.session.delete(r)
            db.session.commit()
            if recipients:
                notify(
                    "Réservation supprimée",
                    (
                        f"Votre réservation du {start_str} au {end_str} "
                        f"(véhicule : {vehicle_info}) a été supprimée par l'administrateur.\n"
                        "Veuillez contacter l'administrateur pour plus d'informations."
                    ),
                    recipients,
                )
            flash("Réservation supprimée.", "info")
            return redirect(url_for("admin_reservations"))
    avail = vehicles_availability(day_start, day_end, exclude_reservation_id=r.id)
    user = current_user()
    return render_template(
        "manage_reservation.html",
        reservation=r,
        availability=avail,
        unavailable=vehicles_unavailability_map(day_start, day_end),
        reserved=vehicles_reserved_map(day_start, day_end),
        user=user,
        current_user=user,
        slot_label=reservation_slot_label,
        day=day,
        is_segment=False,
        segment=None,
    )


@app.route("/admin/manage/segment/<int:sid>", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def manage_segment(sid):
    seg = db.get_or_404(ReservationSegment, sid)
    r = seg.reservation
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update":
            vehicule = form_vehicle()
            if vehicule is None:
                flash("Choisissez un véhicule existant.", "danger")
                return redirect(url_for("manage_segment", sid=seg.id))
            veh_id = vehicule.id
            if has_conflict(
                veh_id, seg.start_at, seg.end_at, exclude_reservation_id=r.id
            ):
                flash("Conflit détecté lors de la modification du segment.", "danger")
            else:
                old_vehicle = seg.vehicle
                seg.vehicle_id = veh_id
                if not commit_if_still_free(veh_id, seg.start_at, seg.end_at, r.id):
                    flash(
                        "Ce véhicule vient d'être attribué par un autre "
                        "administrateur. Choisissez-en un autre.",
                        "danger",
                    )
                    return redirect(url_for("admin_reservations"))
                new_vehicle = db.session.get(Vehicle, veh_id)
                recipients = reservation_notification_recipients(r)
                if recipients:
                    notify(
                        "Véhicule attribué",
                        (
                            f"Véhicule attribué pour votre réservation :\n\n"
                            f"Période : du {seg.start_at.strftime('%d/%m/%Y')} au {seg.end_at.strftime('%d/%m/%Y')}\n"
                            f"Véhicule : {new_vehicle.code}"
                            + (f" ({new_vehicle.label})" if new_vehicle.label else "")
                        ),
                        recipients,
                    )
                flash("Segment mis à jour.", "success")
                return redirect(url_for("admin_reservations"))
        elif action == "delete":
            db.session.delete(seg)
            db.session.commit()
            flash("Segment supprimé.", "info")
            return redirect(url_for("admin_reservations"))
    avail = vehicles_availability(seg.start_at, seg.end_at, exclude_reservation_id=r.id)
    user = current_user()
    return render_template(
        "manage_reservation.html",
        reservation=r,
        availability=avail,
        unavailable=vehicles_unavailability_map(seg.start_at, seg.end_at),
        reserved=vehicles_reserved_map(seg.start_at, seg.end_at),
        user=user,
        current_user=user,
        slot_label=reservation_slot_label,
        day=None,
        is_segment=True,
        segment=seg,
    )


def month_from_args():
    """Année et mois demandés dans l'adresse, ou le mois en cours.

    « ?m=13 » ou « ?y=abc » levaient une erreur 500. Une adresse abîmée —
    tronquée par une messagerie, modifiée à la main — ramène désormais au mois
    en cours plutôt qu'à une page d'erreur.
    """

    aujourdhui = local_now()
    try:
        y = int(request.args.get("y", aujourdhui.year))
        m = int(request.args.get("m", aujourdhui.month))
    except (TypeError, ValueError):
        return aujourdhui.year, aujourdhui.month
    if not (1 <= m <= 12) or not (2000 <= y <= 2100):
        return aujourdhui.year, aujourdhui.month
    return y, m


@app.route("/export/pdf/month")
@role_required("admin", "superadmin")
def export_pdf_month():
    if not WEASY_OK:
        flash("WeasyPrint non installé.", "warning")
        return redirect(url_for("calendar_month"))
    y, m = month_from_args()
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    # Même source que le planning affiché : le PDF oubliait les
    # indisponibilités, qui n'étaient tout simplement pas chargées.
    html = render_template("pdf_month.html", **calendar_payload(start, end))
    pdf = HTML(string=html).write_pdf()
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"planning_{y}-{m:02d}.pdf",
    )


def calendar_payload(start, end):
    """Tout ce qui occupe les véhicules sur la fenêtre ``[start, end)``."""

    vehicles = Vehicle.query.order_by(Vehicle.code).all()
    res = Reservation.query.filter(
        Reservation.status == "approved",
        Reservation.start_at < end,
        Reservation.end_at > start,
    ).all()
    segs = ReservationSegment.query.join(Reservation).filter(
        Reservation.status == "approved",
        ReservationSegment.start_at < end,
        ReservationSegment.end_at > start,
    ).all()
    unavailabilities = VehicleUnavailability.query.filter(
        VehicleUnavailability.start_at < end,
        or_(
            VehicleUnavailability.end_at.is_(None),
            VehicleUnavailability.end_at > start,
        ),
    ).all()
    loans = VehicleLoan.query.filter(
        VehicleLoan.start_at < end,
        VehicleLoan.end_at > start,
    ).order_by(VehicleLoan.start_at).all()
    return {
        "vehicles": vehicles,
        "reservations": res,
        "segments": segs,
        "unavailabilities": unavailabilities,
        "loans": loans,
        "start": start,
        "end": end,
        "timedelta": timedelta,
        "slot_label": reservation_slot_label,
    }


@app.route("/calendar/month")
def calendar_month():
    user = current_user()
    y, m = month_from_args()
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    # Passer en vue semaine ouvre la semaine d'aujourd'hui si le mois affiché
    # la contient, sinon celle du premier du mois.
    aujourdhui = datetime.combine(local_now().date(), time.min)
    pivot = aujourdhui if start <= aujourdhui < end else start
    return render_template(
        "calendar_month.html", user=user, pivot=pivot,
        **calendar_payload(start, end)
    )


@app.route("/calendar/week")
def calendar_week():
    """Le mois entier tient mal sur un écran : sept colonnes larges au lieu
    de trente et une colonnes illisibles."""

    user = current_user()
    jour = request.args.get("d") or ""
    try:
        repere = datetime.strptime(jour, "%Y-%m-%d")
    except ValueError:
        repere = datetime.combine(local_now().date(), time.min)
    start = repere - timedelta(days=repere.weekday())  # lundi
    end = start + timedelta(days=7)
    # Le repère voyage avec la navigation : semaine suivante ou précédente,
    # puis retour au mois, ramènent au mois d'où l'on venait. On reprenait le
    # lundi affiché — pour la semaine du 31 août, « Mois » menait en août.
    return render_template(
        "calendar_week.html", user=user, pivot=repere,
        **calendar_payload(start, end)
    )


# --- Entrée locale de dev (inutile en prod/gunicorn)
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
# TODO: nettoyage login
