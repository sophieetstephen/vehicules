#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from datetime import datetime, timedelta
from io import BytesIO
from forms import LoginForm, FirstLoginForm, RegisterForm, NewRequestForm
from models import db, User, Vehicle, Reservation
from sqlalchemy.exc import IntegrityError

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


# --- Garde: force /login pour les non-connectés (sans boucle)
@app.before_request
def _force_login():
    p = request.path or "/"
    public = {"/login", "/first_login", "/__ping__"}
    if p in public or p.startswith("/static/"):
        return None
    if not session.get("uid"):
        nxt = request.full_path if request.query_string else p
        return redirect(
            "/login" + (f"?next={_urlquote(nxt)}" if nxt else "")
        )
    return None


@app.errorhandler(403)
def forbidden(_):
    return render_template("403.html", user=current_user()), 403


@app.route("/home")
@app.route("/")
def home():
    u = current_user()
    if not u or u.role not in (User.ROLE_ADMIN, User.ROLE_SUPERADMIN):
        return redirect(url_for("calendar_month"))
    return render_template("home.html", user=u, current_user=u)


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
            return redirect(
                request.args.get("next") or url_for("home")
            )
        flash("Identifiants invalides", "danger")
    return render_template("login_plain.html", form=form), 200


@app.route("/logout")
def logout():
    session.pop("uid", None)
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
        user = User(name=name, email=email, role=role)
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


@app.route("/first_login", methods=["GET", "POST"])
def first_login():
    form = FirstLoginForm()
    if form.validate_on_submit():
        name = f"{form.last_name.data} {form.first_name.data}"
        email = form.email.data.lower()
        role = User.ROLE_USER
        if email in app.config.get("SUPERADMIN_EMAILS", []):
            role = User.ROLE_SUPERADMIN
        elif email in app.config.get("ADMIN_EMAILS", []):
            role = User.ROLE_ADMIN
        user = User(name=name, email=email, role=role)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Adresse e‑mail déjà utilisée", "danger")
            return render_template("first_login.html", form=form), 200
        session["uid"] = user.id
        return redirect(url_for("home"))
    return render_template("first_login.html", form=form), 200


@app.route("/request/new", methods=["GET", "POST"])
def new_request():
    form = NewRequestForm()
    if form.validate_on_submit():
        r = Reservation(
            user_id=current_user().id,
            start_at=form.start_at.data,
            end_at=form.end_at.data,
            purpose=form.purpose.data,
            carpool=form.carpool.data,
            carpool_with=form.carpool_with.data,
            notes=form.notes.data,
            status="pending",
        )
        db.session.add(r)
        db.session.commit()
        flash("Votre demande a été transmise.", "success")
        return redirect(url_for("home"))
    return render_template("new_request.html", form=form, user=current_user())


@app.route("/admin/users")
@role_required("admin", "superadmin")
def admin_users():
    u = current_user()
    users = User.query.order_by(User.name).all()
    return render_template(
        "admin_users.html",
        users=users,
        current_user=u,
        user=u,
        ROLE_ADMIN=User.ROLE_ADMIN,
        ROLE_SUPERADMIN=User.ROLE_SUPERADMIN,
    )


@app.route("/admin/promote/<int:user_id>")
@role_required("admin", "superadmin")
def admin_promote(user_id):
    target = User.query.get_or_404(user_id)
    target.role = User.ROLE_ADMIN
    db.session.commit()
    flash("Utilisateur promu administrateur", "success")
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


def vehicles_availability(start, end):
    out = []
    for v in Vehicle.query.order_by(Vehicle.code).all():
        conflict = Reservation.query.filter(
            Reservation.vehicle_id == v.id,
            Reservation.status != "rejected",
            Reservation.end_at > start,
            Reservation.start_at < end,
        ).first()
        out.append((v, conflict is None))
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
    )


@app.route("/admin/manage/<int:rid>", methods=["GET", "POST"])
@role_required("admin", "superadmin")
def manage_request(rid):
    r = Reservation.query.get_or_404(rid)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "approve":
            veh_id = int(request.form.get("vehicle_id"))
            v = Vehicle.query.get_or_404(veh_id)
            conflict = Reservation.query.filter(
                Reservation.vehicle_id == v.id,
                Reservation.status != "rejected",
                Reservation.end_at > r.start_at,
                Reservation.start_at < r.end_at,
                Reservation.id != r.id,
            ).first()
            if conflict:
                flash(
                    "Conflit détecté sur ce véhicule pour la période.", "danger"
                )
            else:
                r.vehicle_id = v.id
                r.status = "approved"
                db.session.commit()
                flash("Demande approuvée et véhicule attribué.", "success")
                return redirect(url_for("admin_reservations"))
        elif action == "reject":
            r.status = "rejected"
            db.session.commit()
            flash("Demande refusée.", "warning")
            return redirect(url_for("admin_reservations"))
    avail = vehicles_availability(r.start_at, r.end_at)
    user = current_user()
    return render_template(
        "manage_request.html",
        r=r,
        availability=avail,
        user=user,
        current_user=user,
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
    return render_template(
        "calendar_month.html",
        vehicles=vehicles,
        reservations=res,
        start=start,
        end=end,
        user=user,
        timedelta=timedelta,
    )


# --- Entrée locale de dev (inutile en prod/gunicorn)
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
# TODO: nettoyage login
