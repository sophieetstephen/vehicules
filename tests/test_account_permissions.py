"""Droits sur les comptes : qui peut agir sur qui.

Audit du 24/09/2026, reproduit : chaque route vérifiait le rôle de celui qui
agit, jamais celui du compte visé. Un administrateur pouvait désactiver le
superadministrateur ou changer son adresse e-mail ; le dernier
superadministrateur pouvait se retirer lui-même tout accès. En plus, trouvé en
corrigeant : « Promouvoir » appliqué à un superadministrateur le rétrogradait
silencieusement en administrateur.
"""

import importlib

import html as html_module

import pytest

from app import app, account_action_refusal
from models import db, User

app_module = importlib.import_module("app")


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


def _user(prenom, role, statut="active"):
    u = User(name=f"X {prenom}", first_name=prenom, last_name="X",
             email=f"{prenom.lower()}@ex.fr", role=role, status=statut, password_hash="x")
    db.session.add(u)
    db.session.flush()
    u.assign_username()
    db.session.commit()
    return u


def _client(u):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = u.id
        s["pwd_stamp"] = u.session_stamp(app.config["SECRET_KEY"])
    return c


def _relire(u):
    db.session.expire_all()
    return db.session.get(User, u.id)


@pytest.fixture
def equipe(ctx):
    return {
        "chef": _user("Chef", User.ROLE_SUPERADMIN),
        "adjoint": _user("Adjoint", User.ROLE_ADMIN),
        "autre_admin": _user("Autre", User.ROLE_ADMIN),
        "jean": _user("Jean", User.ROLE_USER),
    }


# --- un administrateur ne touche pas à ses supérieurs ni à ses pairs ---------

def test_admin_cannot_deactivate_the_superadmin(equipe):
    """Reproduit par l'audit : le compte du chef devenait inactif."""
    _client(equipe["adjoint"]).post(f"/admin/deactivate/{equipe['chef'].id}")
    assert _relire(equipe["chef"]).status == "active"


def test_admin_cannot_change_the_superadmin_email(equipe):
    reponse = _client(equipe["adjoint"]).post(
        f"/admin/user/{equipe['chef'].id}/edit",
        data={"first_name": "Chef", "last_name": "X", "email": "pirate@ex.fr",
              "role": User.ROLE_SUPERADMIN})
    assert reponse.status_code == 302
    assert _relire(equipe["chef"]).email == "chef@ex.fr"


def test_admin_cannot_even_open_the_superadmin_form(equipe):
    reponse = _client(equipe["adjoint"]).get(f"/admin/user/{equipe['chef'].id}/edit")
    assert reponse.status_code == 302


def test_admin_cannot_deactivate_another_admin(equipe):
    _client(equipe["adjoint"]).post(f"/admin/deactivate/{equipe['autre_admin'].id}")
    assert _relire(equipe["autre_admin"]).status == "active"


def test_admin_still_manages_ordinary_users(equipe):
    """Non-régression : c'est son travail quotidien."""
    adjoint = _client(equipe["adjoint"])
    adjoint.post(f"/admin/deactivate/{equipe['jean'].id}")
    assert _relire(equipe["jean"]).status == "inactive"
    adjoint.post(f"/admin/activate/{equipe['jean'].id}")
    assert _relire(equipe["jean"]).status == "active"
    adjoint.post(f"/admin/user/{equipe['jean'].id}/edit",
                 data={"first_name": "Jean", "last_name": "Dupont", "email": "jd@ex.fr",
                       "role": User.ROLE_USER})
    assert _relire(equipe["jean"]).email == "jd@ex.fr"


def test_refusal_is_explained(equipe):
    reponse = _client(equipe["adjoint"]).post(
        f"/admin/deactivate/{equipe['chef'].id}", follow_redirects=True)
    assert "Seul le superadministrateur" in reponse.data.decode()


# --- le dernier superadministrateur ------------------------------------------

def test_last_superadmin_cannot_deactivate_himself(equipe):
    """Sinon plus personne n'a accès à l'administration."""
    _client(equipe["chef"]).post(f"/admin/deactivate/{equipe['chef'].id}")
    assert _relire(equipe["chef"]).status == "active"


def test_last_superadmin_cannot_lose_his_role_through_the_form(equipe):
    _client(equipe["chef"]).post(
        f"/admin/user/{equipe['chef'].id}/edit",
        data={"first_name": "Chef", "last_name": "X", "email": "chef@ex.fr",
              "role": User.ROLE_USER})
    assert _relire(equipe["chef"]).role == User.ROLE_SUPERADMIN


def test_with_two_superadmins_one_may_step_down(equipe):
    """La protection vise le dernier, pas tous."""
    second = _user("Second", User.ROLE_SUPERADMIN)
    _client(equipe["chef"]).post(f"/admin/deactivate/{second.id}")
    assert _relire(second).status == "inactive"


def test_inactive_superadmin_does_not_count(equipe):
    """Un second superadministrateur désactivé ne peut pas reprendre la main."""
    _user("Dormant", User.ROLE_SUPERADMIN, statut="inactive")
    _client(equipe["chef"]).post(f"/admin/deactivate/{equipe['chef'].id}")
    assert _relire(equipe["chef"]).status == "active"


# --- le rôle se change dans « Modifier », et seulement là -----------------------
#
# Il se changeait à deux endroits : la liste de « Modifier » et les boutons
# « Promouvoir » / « Rétrograder » du menu « … ». Un seul chemin reste.

def _modifier(client, cible, role):
    return client.post(f"/admin/user/{cible.id}/edit", data={
        "first_name": cible.first_name, "last_name": cible.last_name,
        "email": cible.email, "role": role}, follow_redirects=True)


def test_superadmin_changes_a_role_from_the_edit_form(equipe):
    chef = _client(equipe["chef"])
    _modifier(chef, equipe["jean"], User.ROLE_ADMIN)
    assert _relire(equipe["jean"]).role == User.ROLE_ADMIN
    _modifier(chef, equipe["jean"], User.ROLE_USER)
    assert _relire(equipe["jean"]).role == User.ROLE_USER


def test_promote_and_demote_routes_are_gone(equipe):
    chef = _client(equipe["chef"])
    for route in ("promote", "demote"):
        assert chef.post(f"/admin/{route}/{equipe['jean'].id}").status_code == 404
    assert _relire(equipe["jean"]).role == User.ROLE_USER


def test_last_superadmin_keeps_the_role_from_the_edit_form(equipe):
    _modifier(_client(equipe["chef"]), equipe["chef"], User.ROLE_ADMIN)
    assert _relire(equipe["chef"]).role == User.ROLE_SUPERADMIN


def test_admin_sees_the_role_but_cannot_change_it(equipe):
    """Un administrateur voyait la liste des rôles ; son choix était ignoré
    sans rien dire."""
    adjoint = _client(equipe["adjoint"])
    page = adjoint.get(f"/admin/user/{equipe['jean'].id}/edit").data.decode()
    assert 'id="role"' not in page, "pas de liste des rôles"
    assert "Seul le superadministrateur change les rôles." in page

    _modifier(adjoint, equipe["jean"], User.ROLE_ADMIN)
    assert _relire(equipe["jean"]).role == User.ROLE_USER


def test_superadmin_cannot_change_his_own_role(equipe):
    """Avec un second superadministrateur, on pouvait se rétrograder soi-même
    d'un mauvais choix dans la liste."""
    _user("Second", User.ROLE_SUPERADMIN)
    chef = _client(equipe["chef"])
    page = chef.get(f"/admin/user/{equipe['chef'].id}/edit").data.decode()
    assert 'id="role"' not in page
    assert "Votre rôle ne peut être changé que par un autre superadministrateur." in html_module.unescape(page)

    _modifier(chef, equipe["chef"], User.ROLE_USER)
    assert _relire(equipe["chef"]).role == User.ROLE_SUPERADMIN


def test_superadmin_can_still_edit_his_own_name(equipe):
    """Le formulaire n'envoie plus de rôle : le reste s'enregistre."""
    chef = _client(equipe["chef"])
    chef.post(f"/admin/user/{equipe['chef'].id}/edit", data={
        "first_name": "Stephen", "last_name": "X", "email": "chef@ex.fr"})
    assert _relire(equipe["chef"]).first_name == "Stephen"
    assert _relire(equipe["chef"]).role == User.ROLE_SUPERADMIN


def test_another_superadmin_can_change_it(equipe):
    second = _user("Second", User.ROLE_SUPERADMIN)
    _modifier(_client(second), equipe["chef"], User.ROLE_ADMIN)
    assert _relire(equipe["chef"]).role == User.ROLE_ADMIN


def test_superadmin_sees_the_role_list(equipe):
    page = _client(equipe["chef"]).get(f"/admin/user/{equipe['jean'].id}/edit").data.decode()
    assert 'id="role"' in page


# --- la règle, directement ---------------------------------------------------

@pytest.mark.parametrize("action", ["edit", "activate", "deactivate",
                                    "reset_password", "delete"])
def test_admin_is_refused_everything_on_the_superadmin(equipe, action):
    assert account_action_refusal(equipe["adjoint"], equipe["chef"], action)


@pytest.mark.parametrize("action", ["reset_password", "delete"])
def test_admin_is_refused_superadmin_only_actions_even_on_users(equipe, action):
    assert account_action_refusal(equipe["adjoint"], equipe["jean"], action)


# --- l'écran suit la règle ---------------------------------------------------

def test_admin_sees_no_action_on_the_superadmin_row(equipe):
    html = _client(equipe["adjoint"]).get("/admin/users").data.decode()
    tableau = html.split("<tbody>")[1].split("</tbody>")[0]
    ligne = [l for l in tableau.split("</tr>") if equipe["chef"].username in l][0]
    assert "Géré par le superadministrateur" in ligne
    assert "/admin/deactivate/" not in ligne
    assert "/edit" not in ligne


def test_superadmin_row_offers_no_self_lockout(equipe):
    html = _client(equipe["chef"]).get("/admin/users").data.decode()
    tableau = html.split("<tbody>")[1].split("</tbody>")[0]
    ligne = [l for l in tableau.split("</tr>") if equipe["chef"].username in l][0]
    assert f"/admin/deactivate/{equipe['chef'].id}" not in ligne
    assert f"/admin/promote/{equipe['chef'].id}" not in ligne
