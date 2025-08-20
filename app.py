#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys
from urllib.parse import quote as _urlquote
from flask import Flask, request, redirect, render_template, flash, session

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
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        # À brancher sur votre vraie logique d'authentification :
        flash("Identifiants invalides", "danger")
    return render_template("login_plain.html"), 200

@app.route("/first_login", methods=["GET", "POST"])
def first_login():
    return "Première connexion — à implémenter", 200

# --- Entrée locale de dev (inutile en prod/gunicorn)
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
# TODO: nettoyage login
