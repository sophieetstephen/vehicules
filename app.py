#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import locale
import os
import sys
from urllib.parse import quote as _urlquote
from functools import wraps
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
)
from datetime import datetime, timedelta, time
from io import BytesIO
from forms import (
    LoginForm,
    RegisterForm,
    ResetPasswordForm,
    NewRequestForm,
    UserForm,
    NotificationSettingsForm,
    ContactForm,
)
from models import db, User, Vehicle, Reservation, ReservationSegment, NotificationSettings
from sqlalchemy.exc import IntegrityError
from notify import send_mail_msmtp
from flask_migrate import Migrate
from utils import reservation_slot_label

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
    class Config:
        SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
        WTF_CSRF_CHECK_DEFAULT = False

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
Migrate(app, db)

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


@app.context_processor
def _inject_locale_helpers():
    return {"weekday_abbr": _weekday_abbr, "month_year_label": _month_year_label}


def purge_expired_requests():
    """Delete pending reservations older than two days."""
    threshold = datetime.utcnow() - timedelta(days=2)
    expired = Reservation.query.filter(
        Reservation.status == "pending",
        Reservation.end_at < threshold,
    )
    count = expired.count()
    if count:
        expired.delete(synchronize_session=False)
        db.session.commit()
    return count


@app.cli.command("purge-expired-requests")
def purge_expired_requests_command():
    """Remove pending reservations older than two days.

    Usage: ``flask purge-expired-requests``
    """
    deleted = purge_expired_requests()
    print(f"Purged {deleted} expired reservation(s).")


def current_user():
    uid = session.get("uid")
    return User.query.get(uid) if uid else None


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


# --- Santé
@app.route("/__ping__", methods=["GET"])
def __ping__():
    return "OK", 200


# --- Gestion de l'expiration de session
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
        "/register",
        "/logout",
        "/__ping__",
        "/home",
        "/",
    }
    if p in public or p.startswith("/static/") or p.startswith("/reset/"):
        return None
    if not session.get("uid"):
        nxt = request.full_path if request.query_string else p
        return redirect(
            "/login" + (f"?next={_urlquote(nxt)}" if nxt else "")
        )
    u = current_user()
    if not u or u.status != "active":
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
    return render_template(template, user=u, current_user=u)


# --- Routes de connexion
@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        u = User.query.filter_by(
            email=form.email.data.lower()
        ).first()
        if u and u.check_password(form.password.data):
            session["uid"] = u.id
            session["last_activity"] = datetime.utcnow().isoformat()
            session.permanent = True
            return redirect(
                request.args.get("next") or url_for("home")
            )
        flash("Identifiants invalides", "danger")
    return render_template("login_plain.html", form=form), 200


@app.route("/logout")
def logout():
    session.pop("uid", None)
    session.pop("last_activity", None)
    flash("Déconnecté", "info")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if form.password.data != form.password2.data:
            flash("Les mots de passe doivent correspondre", "danger")
            return render_template("register.html", form=form), 200
        name = f"{form.last_name.data} {form.first_name.data}"
        email = form.email.data.lower()
        role = User.ROLE_USER
        if email in app.config.get("SUPERADMIN_EMAILS", []):
            role = User.ROLE_SUPERADMIN
        elif email in app.config.get("ADMIN_EMAILS", []):
            role = User.ROLE_ADMIN
        user = User(
            name=name,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=email,
            role=role,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Adresse e‑mail déjà utilisée", "danger")
            return render_template("register.html", form=form), 200
        session["uid"] = user.id
        return redirect(url_for("home"))
    return render_template("register.html", form=form), 200


@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_with_token(token):
    user = User.verify_reset_token(token)
    if not user:
        flash("Lien de réinitialisation invalide ou expiré", "danger")
        return redirect(url_for("login"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Mot de passe mis à jour", "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html", form=form), 200


@app.route("/request/new", methods=["GET", "POST"])
def new_request():
    u = current_user()
    if not u or u.status != "active":
        flash("Compte non activé", "danger")
        return redirect(url_for("home"))
    form = NewRequestForm()
    if form.validate_on_submit():
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
        r = Reservation(
            user_id=current_user().id,
            start_at=start_at,
            end_at=end_at,
            purpose=form.purpose.data,
            carpool=form.carpool.data,
            carpool_with=form.carpool_with.data,
            notes=form.notes.data,
            status="pending",
        )
        db.session.add(r)
        db.session.commit()
        settings = NotificationSettings.query.first()
        recipients = []
        if settings and settings.notify_user_ids:
            recipients = [
                u.email
                for u in User.query.filter(
                    User.id.in_(settings.notify_user_ids),
                    User.status == "active",
                )
            ]
        if recipients:
            recipients = list(set(recipients))
            try:
                send_mail_msmtp(
                    "Demande de réservation",
                    f"Une nouvelle demande a été soumise par {current_user().name}.",
                    recipients,
                )
            except Exception:
                app.logger.exception("Erreur lors de l'envoi du mail")
        try:
            send_mail_msmtp(
                "Demande de réservation reçue",
                (
                    f"Nous avons bien reçu votre demande de réservation du "
                    f"{start_at.strftime('%d/%m/%Y %H:%M')} au {end_at.strftime('%d/%m/%Y %H:%M')}. "
                    "Elle est en attente de validation."
                ),
                current_user().email,
            )
        except Exception:
            app.logger.exception("Erreur lors de l'envoi du mail")
        flash("Votre demande a été transmise.", "success")
        return redirect(url_for("home"))
    return render_template("new_request.html", form=form, user=current_user())


@app.route("/contact", methods=["GET", "POST"])
@role_required(User.ROLE_USER, User.ROLE_ADMIN, User.ROLE_SUPERADMIN)
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        settings = NotificationSettings.query.first()
        recipients = []
        if settings and settings.notify_user_ids:
            recipients = [
                u.email
                for u in User.query.filter(
                    User.id.in_(settings.notify_user_ids),
                    User.status == "active",
                )
            ]
        if recipients:
            recipients = list(set(recipients))
            u = current_user()
            body_admin = (
                f"{form.message.data}\n\n"
                f"Nom : {u.last_name}\n"
                f"Prénom : {u.first_name}\n"
                f"Email : {u.email}"
            )
            try:
                send_mail_msmtp(
                    "Message de contact",
                    body_admin,
                    recipients,
                )
            except Exception:
                app.logger.exception("Erreur lors de l'envoi du mail")
        try:
            send_mail_msmtp(
                "Confirmation de message",
                "Votre message a bien été envoyé à l'Administrateur, vous recevrez prochainement une réponse.",
                current_user().email,
            )
        except Exception:
            app.logger.exception("Erreur lors de l'envoi du mail")
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


@app.route("/admin/user/<int:user_id>/edit", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def admin_user_edit(user_id):
    target = User.query.get_or_404(user_id)
    u = current_user()
    form = UserForm(obj=target)
    if form.validate_on_submit():
        target.first_name = form.first_name.data
        target.last_name = form.last_name.data
        target.name = f"{form.last_name.data} {form.first_name.data}"
        target.email = form.email.data.lower()
        if current_user().role == User.ROLE_SUPERADMIN:
            target.role = form.role.data
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


@app.route("/admin/promote/<int:user_id>")
@role_required("superadmin")
def admin_promote(user_id):
    target = User.query.get_or_404(user_id)
    target.role = User.ROLE_ADMIN
    db.session.commit()
    flash("Utilisateur promu administrateur", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/demote/<int:user_id>")
@role_required("superadmin")
def admin_demote(user_id):
    target = User.query.get_or_404(user_id)
    target.role = User.ROLE_USER
    db.session.commit()
    flash("Utilisateur rétrogradé", "info")
    return redirect(url_for("admin_users"))


@app.route("/admin/activate/<int:user_id>")
@role_required("admin", "superadmin")
def admin_activate(user_id):
    target = User.query.get_or_404(user_id)
    target.status = "active"
    db.session.commit()
    flash("Utilisateur activé", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/deactivate/<int:user_id>")
@role_required("admin", "superadmin")
def admin_deactivate(user_id):
    target = User.query.get_or_404(user_id)
    target.status = "inactive"
    db.session.commit()
    flash("Utilisateur désactivé", "warning")
    return redirect(url_for("admin_users"))


@app.route("/admin/reset_password/<int:user_id>", methods=["POST"])
@role_required("superadmin")
def admin_reset_password(user_id):
    target = User.query.get_or_404(user_id)
    token = target.generate_reset_token()
    reset_url = url_for("reset_with_token", token=token, _external=True)
    try:
        send_mail_msmtp(
            "Réinitialisation de mot de passe",
            f"Bonjour, pour réinitialiser votre mot de passe, suivez ce lien : {reset_url}",
            target.email,
        )
    except Exception:
        pass
    flash("Lien de réinitialisation envoyé", "info")
    return redirect(url_for("admin_users"))


@app.route("/admin/delete/<int:user_id>")
@role_required("superadmin")
def admin_user_delete(user_id):
    target = User.query.get_or_404(user_id)
    if target.role == User.ROLE_SUPERADMIN:
        flash("Impossible de supprimer un superadministrateur", "danger")
        return redirect(url_for("admin_users"))
    # Suppression en cascade des réservations associées
    Reservation.query.filter_by(user_id=target.id).delete()
    db.session.delete(target)
    db.session.commit()
    flash("Utilisateur supprimé", "info")
    return redirect(url_for("admin_users"))


@app.route("/admin/vehicles")
@role_required("admin", "superadmin")
def admin_vehicles():
    user = current_user()
    vehicles = Vehicle.query.order_by(Vehicle.code).all()
    return render_template(
        "admin_vehicles.html",
        vehicles=vehicles,
        user=user,
        current_user=user,
    )


@app.route("/admin/vehicles/new", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def admin_vehicle_new():
    if request.method == "POST":
        v = Vehicle(
            code=request.form["code"].strip(),
            label=request.form["label"].strip(),
            category=request.form.get("category", "").strip() or None,
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
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if request.method == "POST":
        vehicle.code = request.form["code"].strip()
        vehicle.label = request.form["label"].strip()
        vehicle.category = request.form.get("category", "").strip() or None
        db.session.commit()
        flash("Véhicule mis à jour", "success")
        return redirect(url_for("admin_vehicles"))
    return render_template(
        "vehicle_form.html", vehicle=vehicle, user=current_user()
    )


@app.route("/admin/vehicles/<int:vehicle_id>/delete")
@role_required("admin", "superadmin")
def admin_vehicle_delete(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    db.session.delete(vehicle)
    db.session.commit()
    flash("Véhicule supprimé", "info")
    return redirect(url_for("admin_vehicles"))


def has_conflict(vehicle_id, start, end, exclude_reservation_id=None):
    q_seg = ReservationSegment.query.filter(
        ReservationSegment.vehicle_id == vehicle_id,
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
        Reservation.status != "rejected",
        Reservation.end_at > start,
        Reservation.start_at < end,
    )
    if exclude_reservation_id is not None:
        q_res = q_res.filter(Reservation.id != exclude_reservation_id)
    return q_res.first() is not None


def vehicles_availability(start, end):
    out = []
    for v in Vehicle.query.order_by(Vehicle.code).all():
        conflict = has_conflict(v.id, start, end)
        out.append((v, not conflict))
    return out


@app.route("/admin/reservations")
@role_required("admin", "superadmin")
def admin_reservations():
    user = current_user()
    res = (
        Reservation.query.order_by(Reservation.start_at.desc()).limit(200).all()
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
    r = Reservation.query.get_or_404(rid)
    day_str = request.args.get("day")
    day = None
    if day_str:
        day = datetime.strptime(day_str, "%Y-%m-%d")
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
            veh_id = int(request.form.get("vehicle_id"))
            if has_conflict(
                veh_id, day_start, day_end, exclude_reservation_id=r.id
            ):
                flash("Conflit détecté lors de la création du segment.", "danger")
            else:
                existing = ReservationSegment.query.filter(
                    ReservationSegment.reservation_id == r.id,
                    ReservationSegment.end_at > day_start,
                    ReservationSegment.start_at < day_end,
                ).first()
                if existing:
                    old_vehicle = Vehicle.query.get(existing.vehicle_id)
                    existing.vehicle_id = veh_id
                    db.session.commit()
                    new_vehicle = Vehicle.query.get(veh_id)
                    try:
                        send_mail_msmtp(
                            "Réservation validée",
                            (
                                f"Le segment du {existing.start_at.strftime('%d/%m/%Y %H:%M')} au "
                                f"{existing.end_at.strftime('%d/%m/%Y %H:%M')} a été mis à jour.\n"
                                f"Ancien véhicule : {old_vehicle.label if old_vehicle else 'N/A'}.\n"
                                f"Nouveau véhicule : {new_vehicle.label}."
                            ),
                            r.user.email,
                        )
                    except Exception:
                        app.logger.exception("Erreur lors de l'envoi du mail")
                    flash("Segment mis à jour.", "success")
                    return redirect(url_for("admin_reservations"))
                seg = ReservationSegment(
                    reservation_id=r.id,
                    vehicle_id=veh_id,
                    start_at=day_start,
                    end_at=day_end,
                )
                db.session.add(seg)
                old_vehicle = r.vehicle_id
                if old_vehicle is not None:
                    db.session.flush()
                    segments = ReservationSegment.query.filter_by(reservation_id=r.id).all()
                    covered_dates = {s.start_at.date() for s in segments}
                    current_date = r.start_at.date()
                    end_date = r.end_at.date()
                    while current_date <= end_date:
                        if current_date not in covered_dates:
                            day_start_fill = datetime.combine(current_date, time.min)
                            day_end_fill = datetime.combine(current_date, time.max)
                            if current_date == r.start_at.date():
                                day_start_fill = r.start_at
                            if current_date == r.end_at.date():
                                day_end_fill = r.end_at
                            db.session.add(
                                ReservationSegment(
                                    reservation_id=r.id,
                                    vehicle_id=old_vehicle,
                                    start_at=day_start_fill,
                                    end_at=day_end_fill,
                                )
                            )
                        current_date += timedelta(days=1)
                    r.vehicle_id = None
                r.status = "approved"
                db.session.commit()
                vehicle = Vehicle.query.get(veh_id)
                try:
                    send_mail_msmtp(
                        "Réservation validée",
                        (
                            f"Un segment du {day_start.strftime('%d/%m/%Y %H:%M')} au "
                            f"{day_end.strftime('%d/%m/%Y %H:%M')} vous a été attribué avec le véhicule {vehicle.label}."
                        ),
                        r.user.email,
                    )
                except Exception:
                    app.logger.exception("Erreur lors de l'envoi du mail")
                flash("Segment ajouté.", "success")
                return redirect(url_for("admin_reservations"))
        elif action == "delete_day" and day:
            existing = ReservationSegment.query.filter(
                ReservationSegment.reservation_id == r.id,
                ReservationSegment.end_at > day_start,
                ReservationSegment.start_at < day_end,
            ).first()
            if existing:
                db.session.delete(existing)
            else:
                old_vehicle = r.vehicle_id
                if old_vehicle is not None:
                    current_date = r.start_at.date()
                    end_date = r.end_at.date()
                    while current_date <= end_date:
                        if current_date != day_start.date():
                            day_start_fill = datetime.combine(current_date, time.min)
                            day_end_fill = datetime.combine(current_date, time.max)
                            if current_date == r.start_at.date():
                                day_start_fill = r.start_at
                            if current_date == r.end_at.date():
                                day_end_fill = r.end_at
                            db.session.add(
                                ReservationSegment(
                                    reservation_id=r.id,
                                    vehicle_id=old_vehicle,
                                    start_at=day_start_fill,
                                    end_at=day_end_fill,
                                )
                            )
                        current_date += timedelta(days=1)
                    r.vehicle_id = None
            r.status = "approved"
            db.session.commit()
            flash("Journée supprimée.", "info")
            return redirect(url_for("admin_reservations"))
        if action == "approve":
            veh_id = int(request.form.get("vehicle_id"))
            v = Vehicle.query.get_or_404(veh_id)
            if has_conflict(v.id, r.start_at, r.end_at, exclude_reservation_id=r.id):
                flash(
                    "Conflit détecté sur ce véhicule pour la période.", "danger"
                )
            else:
                r.vehicle_id = v.id
                r.status = "approved"
                db.session.commit()
                try:
                    send_mail_msmtp(
                        "Réservation validée",
                        (
                            f"Votre réservation du {r.start_at.strftime('%d/%m/%Y %H:%M')} au "
                            f"{r.end_at.strftime('%d/%m/%Y %H:%M')} a été validée.\n"
                            f"Véhicule attribué : {v.label}."
                        ),
                        r.user.email,
                    )
                except Exception:
                    app.logger.exception("Erreur lors de l'envoi du mail")
                flash("Demande approuvée et véhicule attribué.", "success")
                return redirect(url_for("admin_reservations"))
        elif action == "segment":
            start_at = datetime.fromisoformat(request.form.get("start_at"))
            end_at = datetime.fromisoformat(request.form.get("end_at"))
            veh_id = int(request.form.get("vehicle_id"))
            if has_conflict(veh_id, start_at, end_at, exclude_reservation_id=r.id):
                flash("Conflit détecté lors de la création du segment.", "danger")
            else:
                seg = ReservationSegment(
                    reservation_id=r.id,
                    vehicle_id=veh_id,
                    start_at=start_at,
                    end_at=end_at,
                )
                r.vehicle_id = None
                r.status = "approved"
                db.session.add(seg)
                db.session.commit()
                vehicle = Vehicle.query.get(veh_id)
                try:
                    send_mail_msmtp(
                        "Réservation validée",
                        (
                            f"Un segment du {start_at.strftime('%d/%m/%Y %H:%M')} au "
                            f"{end_at.strftime('%d/%m/%Y %H:%M')} a été attribué au véhicule {vehicle.label}."
                        ),
                        r.user.email,
                    )
                except Exception:
                    app.logger.exception("Erreur lors de l'envoi du mail")
                flash("Segment ajouté.", "success")
                return redirect(url_for("admin_reservations"))
        elif action == "reject":
            r.status = "rejected"
            db.session.commit()
            flash("Demande refusée.", "warning")
            return redirect(url_for("admin_reservations"))
        elif action == "delete":
            db.session.delete(r)
            db.session.commit()
            flash("Réservation supprimée.", "info")
            return redirect(url_for("admin_reservations"))
    avail = vehicles_availability(day_start, day_end)
    user = current_user()
    return render_template(
        "manage_request.html",
        r=r,
        availability=avail,
        user=user,
        current_user=user,
        slot_label=reservation_slot_label,
        day=day,
    )


@app.route("/admin/manage/segment/<int:sid>", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def manage_segment(sid):
    seg = ReservationSegment.query.get_or_404(sid)
    r = seg.reservation
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update":
            veh_id = int(request.form.get("vehicle_id"))
            if has_conflict(
                veh_id, seg.start_at, seg.end_at, exclude_reservation_id=r.id
            ):
                flash("Conflit détecté lors de la modification du segment.", "danger")
            else:
                old_vehicle = seg.vehicle
                seg.vehicle_id = veh_id
                db.session.commit()
                new_vehicle = Vehicle.query.get(veh_id)
                try:
                    send_mail_msmtp(
                        "Modification de votre réservation",
                        (
                            f"Le segment du {seg.start_at.strftime('%d/%m/%Y %H:%M')} au "
                            f"{seg.end_at.strftime('%d/%m/%Y %H:%M')} a été mis à jour.\n"
                            f"Ancien véhicule : {old_vehicle.label if old_vehicle else 'N/A'}.\n"
                            f"Nouveau véhicule : {new_vehicle.label}."
                        ),
                        r.user.email,
                    )
                except Exception:
                    app.logger.exception("Erreur lors de l'envoi du mail")
                flash("Segment mis à jour.", "success")
                return redirect(url_for("admin_reservations"))
        elif action == "delete":
            db.session.delete(seg)
            db.session.commit()
            flash("Segment supprimé.", "info")
            return redirect(url_for("admin_reservations"))
    avail = vehicles_availability(seg.start_at, seg.end_at)
    user = current_user()
    return render_template(
        "manage_segment.html",
        seg=seg,
        availability=avail,
        user=user,
        current_user=user,
        slot_label=reservation_slot_label,
    )


@app.route("/export/pdf/month")
@role_required("admin", "superadmin")
def export_pdf_month():
    if not WEASY_OK:
        flash("WeasyPrint non installé.", "warning")
        return redirect(url_for("calendar_month"))
    y = int(request.args.get("y", datetime.today().year))
    m = int(request.args.get("m", datetime.today().month))
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    vehicles = Vehicle.query.order_by(Vehicle.code).all()
    res = Reservation.query.filter(
        Reservation.status == "approved",
        Reservation.start_at < end,
        Reservation.end_at > start,
    ).all()
    html = render_template(
        "pdf_month.html",
        vehicles=vehicles,
        reservations=res,
        start=start,
        end=end,
        slot_label=reservation_slot_label,
        timedelta=timedelta,
    )
    pdf = HTML(string=html).write_pdf()
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"planning_{y}-{m:02d}.pdf",
    )


@app.route("/calendar/month")
def calendar_month():
    user = current_user()
    y = int(request.args.get("y", datetime.today().year))
    m = int(request.args.get("m", datetime.today().month))
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
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
    return render_template(
        "calendar_month.html",
        vehicles=vehicles,
        reservations=res,
        segments=segs,
        start=start,
        end=end,
        user=user,
        timedelta=timedelta,
        slot_label=reservation_slot_label,
    )


# --- Entrée locale de dev (inutile en prod/gunicorn)
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
# TODO: nettoyage login
