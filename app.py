#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys
from urllib.parse import quote as _urlquote
from flask import Flask, request, redirect, render_template, flash, session, url_for
from forms import FirstLoginForm
from models import db, User
from sqlalchemy.exc import IntegrityError

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

# --- Santé
@app.route("/__ping__", methods=["GET"])
def __ping__():
    return "OK", 200

# --- Garde: force /login_plain pour les non-connectés (sans boucle)
@app.before_request
def _force_login_plain():
    p = request.path or "/"
    public = {"/login", "/login_plain", "/first_login", "/__ping__"}
    if p in public or p.startswith("/static/"):
        return None
    if not session.get("uid"):
        nxt = request.full_path if request.query_string else p
        return redirect("/login_plain" + (f"?next={_urlquote(nxt)}" if nxt else ""))
    return None

# --- Routes de connexion
@app.route("/login", methods=["GET", "POST"])
def login():
    # alias → page simple
    return redirect("/login_plain")

@app.route("/login_plain", methods=["GET", "POST"])
def login_plain():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        u = User.query.filter_by(email=email).first()
        if u and u.check_password(password):
            session["uid"] = u.id
            return redirect(request.args.get("next") or url_for("home"))
        flash("Identifiants invalides", "danger")
    return render_template("login_plain.html"), 200

@app.route("/first_login", methods=["GET", "POST"])
def first_login():
    form = FirstLoginForm()
    if form.validate_on_submit():
        name = f"{form.last_name.data} {form.first_name.data}"
        user = User(name=name, email=form.email.data.lower())
        user.set_password(form.password.data)
        if form.email.data in app.config.get("ADMIN_EMAILS", []):
            user.role = "admin"
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Adresse e‑mail déjà utilisée", "danger")
            return render_template("first_login.html", form=form), 200
        session["uid"] = user.id
        return redirect("/")
    return render_template("first_login.html", form=form), 200

# --- Entrée locale de dev (inutile en prod/gunicorn)
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
# TODO: nettoyage login
