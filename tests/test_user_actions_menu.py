"""Actions d'un utilisateur : une visible, les autres dans un menu.

Chaque ligne du tableau portait jusqu'à cinq boutons (Modifier, Désactiver,
Régénérer MDP, Promouvoir, Supprimer). Ils repassaient sur deux rangées et
rendaient la liste illisible. Le tableau et les cartes du téléphone les
définissaient chacun de leur côté, avec des libellés déjà divergents.
"""

import importlib
import os
import pathlib
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from models import db, User

app_module = importlib.import_module("app")

ACTIONS = ["Désactiver", "Régénérer le mot de passe", "Promouvoir", "Supprimer"]


@pytest.fixture
def ctx(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.drop_all()


def _user(first, last, email, role=User.ROLE_USER, status="active"):
    u = User(name=f"{last} {first}", first_name=first, last_name=last, email=email,
             role=role, status=status, password_hash="x")
    db.session.add(u)
    db.session.flush()
    u.assign_username()
    db.session.commit()
    return u


def _client_as(user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = user.id
        s["pwd_stamp"] = user.session_stamp(app.config["SECRET_KEY"])
    return c


def _page(patron):
    _user("Jean", "Dupont", "j@ex.fr")
    return _client_as(patron).get("/admin/users").data.decode()


def _ligne(html, identifiant):
    """La ligne du tableau portant cet identifiant.

    L'ordre des lignes dépend du tri : viser « la première » revenait à tomber
    sur la ligne du superadmin lui-même, qui n'offre ni promotion ni
    suppression.
    """
    tableau = html.split("<tbody>")[1].split("</tbody>")[0]
    for ligne in tableau.split("</tr>"):
        if f">{identifiant}<" in ligne:
            return ligne
    raise AssertionError(f"ligne {identifiant} absente")


def _menu(html, identifiant="dupontj"):
    """Le menu d'une ligne — pas celui de la barre du haut, qui vient avant."""
    return _ligne(html, identifiant).split('<ul class="dropdown-menu')[1].split("</ul>")[0]


# --- ce que la ligne montre --------------------------------------------------

def test_only_one_action_stays_visible(ctx):
    """« Modifier » est le geste courant : lui seul reste sous les yeux."""
    patron = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_SUPERADMIN)
    html = _page(patron)
    ligne = _ligne(html, "dupontj")
    boutons = ligne.count('class="btn btn-sm')
    assert boutons == 2, f"{boutons} boutons visibles, attendus : Modifier et le menu"
    assert "Modifier" in ligne
    assert 'data-bs-toggle="dropdown"' in ligne


def test_hidden_actions_moved_to_the_menu(ctx):
    patron = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_SUPERADMIN)
    html = _page(patron)
    menu = _menu(html)
    for action in ACTIONS:
        assert action in menu, action
    # La suppression est isolée du reste : on ne la clique pas par mégarde.
    assert menu.index("dropdown-divider") < menu.index("Supprimer")


def test_menu_is_reachable_without_a_mouse(ctx):
    patron = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_SUPERADMIN)
    html = _page(patron)
    bouton = _ligne(html, "dupontj").split("<button", 1)[1].split(">")[0]
    assert "aria-label=" in bouton, "un bouton « … » sans énoncé est muet au lecteur d'écran"
    assert 'aria-label="Autres actions pour Jean Dupont"' in _ligne(html, "dupontj")


# --- qui voit quoi -----------------------------------------------------------

def test_admin_sees_only_what_he_may_do(ctx):
    """Un admin simple ne régénère pas les mots de passe et ne promeut personne."""
    patron = _user("Marc", "Adjoint", "adj@ex.fr", role=User.ROLE_ADMIN)
    html = _page(patron)
    menu = _menu(html)
    assert "Désactiver" in menu
    for interdit in ("Régénérer", "Promouvoir", "Supprimer"):
        assert interdit not in menu, interdit


def test_superadmin_row_offers_no_self_destruction(ctx):
    """On ne se rétrograde ni ne se supprime soi-même depuis la liste."""
    patron = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_SUPERADMIN)
    html = _page(patron)
    # La ligne du superadmin est celle qui porte son identifiant.
    sienne = _ligne(html, "chefa")
    assert "Supprimer" not in sienne
    assert "Rétrograder" not in sienne
    assert "Régénérer le mot de passe" in sienne


def test_inactive_user_is_offered_reactivation(ctx):
    patron = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_SUPERADMIN)
    _user("Luc", "Bernard", "b@ex.fr", status="inactive")
    html = _client_as(patron).get("/admin/users").data.decode()
    sienne = _ligne(html, "bernardl")
    assert "Activer" in sienne and "Désactiver" not in sienne


# --- les actions marchent toujours -------------------------------------------

def test_menu_actions_still_reach_their_route(ctx):
    """Le menu n'est qu'une présentation : les formulaires restent des POST."""
    patron = _user("Alex", "Chef", "chef@ex.fr", role=User.ROLE_SUPERADMIN)
    cible = _user("Jean", "Dupont", "j@ex.fr")
    c = _client_as(patron)
    html = c.get("/admin/users").data.decode()
    for route in (f"/admin/deactivate/{cible.id}",
                  f"/admin/reset_password/{cible.id}",
                  f"/admin/promote/{cible.id}",
                  f"/admin/delete/{cible.id}"):
        assert route in html, route

    assert c.post(f"/admin/deactivate/{cible.id}", follow_redirects=True).status_code == 200
    assert db.session.get(User, cible.id).status == "inactive"


# --- une seule définition pour les deux affichages ---------------------------

def test_table_and_phone_share_one_definition():
    """Les deux listes divergeaient déjà : le tableau disait « Régénérer MDP »,
    la carte affichait une corbeille sans libellé."""
    gabarit = pathlib.Path("templates/admin_users.html").read_text(encoding="utf-8")
    assert gabarit.count('include "_user_actions.html"') == 2
    # Le texte d'aide cite le libellé du menu : on ne regarde que les listes.
    listes = gabarit.split("<!-- ========== VUE DESKTOP")[1].split("<style>")[0]
    for action in ACTIONS:
        assert action not in listes, f"{action} redéfini hors du bloc partagé"


def test_menu_escapes_the_scrolling_table():
    """Le tableau défile horizontalement : sans stratégie « fixed », le menu
    des dernières lignes était coupé par le bord du conteneur."""
    gabarit = pathlib.Path("templates/admin_users.html").read_text(encoding="utf-8")
    assert "strategy: 'fixed'" in gabarit
    # Bootstrap est chargé en fin de page : le script doit attendre le DOM.
    assert gabarit.index("DOMContentLoaded") < gabarit.index("strategy: 'fixed'")
