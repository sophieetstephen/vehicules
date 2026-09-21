"""Navigation courte et permanente dans la barre du haut.

Auparavant la barre ne contenait aucun lien : passer d'une section à une autre
imposait de revenir à l'accueil par la marque, puis de cliquer une tuile. Les
pages sans issue (formulaire, contact) n'offraient aucun autre chemin.
"""

import os
import sys

import pytest
from flask import render_template

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app
from models import User

LIENS = [("Accueil", "/"), ("Planning", "/calendar/month"), ("Réserver", "/request/new")]


def _nav(role: str, chemin: str = "/") -> str:
    with app.test_request_context(chemin):
        user = User(
            name="Test User",
            first_name="Test",
            last_name="User",
            email="test@example.com",
            role=role,
            password_hash="x",
        )
        return render_template("base.html", user=user)


@pytest.mark.parametrize("role", [User.ROLE_SUPERADMIN, User.ROLE_ADMIN, User.ROLE_USER])
def test_three_links_for_every_role(role):
    """Les trois destinations sont accessibles à tous les rôles."""
    html = _nav(role)
    bloc = html.split('class="navbar-nav nav-main')[1].split("</ul>")[0]
    for libelle, chemin in LIENS:
        assert libelle in bloc, libelle
        assert f'href="{chemin}"' in bloc, chemin
    assert bloc.count("nav-item") == 3, "la barre doit rester courte"


@pytest.mark.parametrize("role", [User.ROLE_SUPERADMIN, User.ROLE_ADMIN, User.ROLE_USER])
def test_user_menu_and_brand_kept(role):
    html = _nav(role)
    assert "navbar-brand-custom" in html
    assert "Déconnexion" in html


def test_no_links_when_not_logged_in():
    with app.test_request_context("/login"):
        html = render_template("base.html", user=None)
    assert "nav-main" not in html
    assert "Connexion" in html


@pytest.mark.parametrize("chemin,attendu", [
    ("/", "Accueil"),
    ("/calendar/month", "Planning"),
    ("/request/new", "Réserver"),
])
def test_current_page_is_marked(chemin, attendu):
    """La page courante est signalée, pour savoir où l'on se trouve."""
    html = _nav(User.ROLE_USER, chemin)
    bloc = html.split('class="navbar-nav nav-main')[1].split("</ul>")[0]
    actif = [m for m in bloc.split("<li") if "active" in m]
    assert len(actif) == 1, "un seul lien actif à la fois"
    assert attendu in actif[0]
    assert 'aria-current="page"' in actif[0]


def test_labels_kept_under_icons_on_phones():
    """Une icône seule se devine mal : le libellé reste, en petit, dessous."""
    import pathlib
    css = pathlib.Path("static/custom.css").read_text(encoding="utf-8")
    petit = css.split("@media (max-width: 575.98px)")[1]

    lien = petit.split(".nav-main .nav-link {")[1].split("}")[0]
    assert "flex-direction: column" in lien, "icône au-dessus, libellé dessous"
    # Cible tactile confortable, l'application s'utilise parfois avec des gants.
    assert "padding: 0.5rem" in lien

    libelle = petit.split(".nav-main .nav-label {")[1].split("}")[0]
    assert "display: block" in libelle
    assert "display: none" not in libelle

    # Seul le nom de l'application disparaît, pour laisser la place.
    marque = petit.split(".navbar-brand-custom .brand-name {")[1].split("}")[0]
    assert "display: none" in marque


# --- les tuiles de l'accueil restent la porte d'entrée principale -----------

def _render_home(role: str) -> str:
    templates = {
        User.ROLE_SUPERADMIN: "superadmin_home.html",
        User.ROLE_ADMIN: "admin_home.html",
        User.ROLE_USER: "user_home.html",
    }
    with app.test_request_context("/"):
        user = User(
            name="Test User",
            first_name="Test",
            last_name="User",
            email="test@example.com",
            role=role,
            password_hash="x",
        )
        return render_template(templates[role], user=user, current_user=user)


@pytest.mark.parametrize(
    "role,links",
    [
        (User.ROLE_USER, ["Planning mensuel", "Nouvelle réservation", "Contact"]),
        (
            User.ROLE_ADMIN,
            ["Gestion du parc", "Gestion des réservations", "Planning mensuel", "Nouvelle réservation"],
        ),
        (
            User.ROLE_SUPERADMIN,
            [
                "Gestion des utilisateurs",
                "Gestion du parc",
                "Gestion des réservations",
                "Gestion des congés",
                "Planning mensuel",
                "Nouvelle réservation",
            ],
        ),
    ],
)
def test_home_tabs_by_role(role, links):
    html = _render_home(role)
    for link in links:
        assert html.count(f'<h5 class="card-title">{link}</h5>') == 1
