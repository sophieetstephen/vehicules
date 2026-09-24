"""Limitation des tentatives de connexion (blocage temporaire après échecs)."""

from datetime import datetime, timedelta

import pytest

from app import app, login_blocked_minutes
from models import db, User, LoginAttempt

PASSWORD = "Kx7m-Rp2v-Q9wT"


@pytest.fixture
def ctx():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["LOGIN_MAX_ATTEMPTS"] = 5
    app.config["LOGIN_LOCKOUT_MINUTES"] = 15
    app.config["LOGIN_IP_MAX_ATTEMPTS"] = 30
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        u = User(name="Dupont Jean", first_name="Jean", last_name="Dupont", username="dupontj",
                 email="j@ex.fr", role=User.ROLE_USER, status="active")
        u.set_password(PASSWORD)
        db.session.add(u)
        db.session.commit()
        yield u
        db.drop_all()


def _login(client, username, password, ip="10.0.0.1"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        headers={"X-Forwarded-For": ip},
    )


def test_lockout_after_five_failures_even_with_correct_password(ctx):
    client = app.test_client()
    for _ in range(5):
        resp = _login(client, "dupontj", "mauvais")
        assert resp.status_code == 200 and "Identifiant ou mot de passe incorrect" in resp.data.decode()
    assert LoginAttempt.query.filter_by(username="dupontj", success=False).count() == 5

    resp = _login(client, "DupontJ", PASSWORD)  # bon mot de passe, mais bloqué
    assert resp.status_code == 429
    html = resp.data.decode()
    assert "Trop de tentatives" in html and "15 minutes" in html
    with client.session_transaction() as s:
        assert "uid" not in s
    # Une tentative pendant le blocage n'est pas comptée.
    assert LoginAttempt.query.filter_by(username="dupontj").count() == 5


def test_lock_expires_after_window(ctx):
    client = app.test_client()
    for _ in range(5):
        _login(client, "dupontj", "mauvais")
    assert login_blocked_minutes("dupontj", "10.0.0.1") == 15
    # 16 minutes plus tard : les échecs sont hors fenêtre.
    for a in LoginAttempt.query.all():
        a.created_at = datetime.utcnow() - timedelta(minutes=16)
    db.session.commit()
    assert login_blocked_minutes("dupontj", "10.0.0.1") == 0
    resp = _login(client, "dupontj", PASSWORD)
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert s["uid"] == ctx.id


def test_remaining_minutes_decrease(ctx):
    client = app.test_client()
    for _ in range(5):
        _login(client, "dupontj", "mauvais")
    for a in LoginAttempt.query.all():
        a.created_at = datetime.utcnow() - timedelta(minutes=10, seconds=30)
    db.session.commit()
    assert login_blocked_minutes("dupontj", None) == 5


def test_success_resets_failure_counter(ctx):
    client = app.test_client()
    for _ in range(4):
        _login(client, "dupontj", "mauvais")
    resp = _login(client, "dupontj", PASSWORD)
    assert resp.status_code == 302
    assert LoginAttempt.query.filter_by(username="dupontj", success=False).count() == 0
    assert LoginAttempt.query.filter_by(username="dupontj", success=True).count() == 1
    client.get("/logout")
    for _ in range(4):
        _login(client, "dupontj", "mauvais")
    assert _login(client, "dupontj", PASSWORD).status_code == 302


def test_unknown_identifier_is_locked_too_without_revealing_it(ctx):
    """Les messages, essais restants compris, ne doivent pas trahir qu'un
    identifiant existe : on les compare mot pour mot avec un compte réel."""
    import re

    def message(html):
        return re.search(r'class="alert[^"]*">\s*<i[^>]*></i>\s*(.*?)\s*</div>', html, re.S).group(1)

    inconnu, reel = app.test_client(), app.test_client()
    for _ in range(5):
        a = message(_login(inconnu, "inconnu", "x", ip="192.0.2.1").data.decode())
        b = message(_login(reel, "dupontj", "x", ip="192.0.2.2").data.decode())
        assert "Identifiant ou mot de passe incorrect" in a
        assert a == b, "même message pour un compte existant ou non"
    assert _login(inconnu, "inconnu", "x", ip="192.0.2.1").status_code == 429


def test_lock_is_per_identifier(ctx):
    client = app.test_client()
    for _ in range(5):
        _login(client, "autre", "x")
    assert _login(client, "dupontj", PASSWORD).status_code == 302


def test_ip_lockout_across_identifiers(ctx):
    app.config["LOGIN_IP_MAX_ATTEMPTS"] = 8
    client = app.test_client()
    for i in range(8):
        _login(client, f"compte{i}", "x", ip="203.0.113.7")
    # Même IP : bloquée quel que soit l'identifiant, même valide.
    assert _login(client, "dupontj", PASSWORD, ip="203.0.113.7").status_code == 429
    # Autre IP : pas concernée.
    assert _login(client, "dupontj", PASSWORD, ip="203.0.113.8").status_code == 302


def test_client_ip_is_the_one_seen_by_the_proxy(ctx):
    """Chaque proxy ajoute à X-Forwarded-For l'adresse qu'il a vue. Avec Caddy
    seul devant l'application, c'est la dernière valeur qui est fiable ; les
    précédentes viennent du client."""
    client = app.test_client()
    _login(client, "dupontj", "x", ip="198.51.100.4, 10.0.0.2")
    assert LoginAttempt.query.first().ip == "10.0.0.2"
    client.post("/login", data={"username": "dupontj", "password": "x"},
                environ_base={"REMOTE_ADDR": "192.0.2.9"})
    assert LoginAttempt.query.order_by(LoginAttempt.id.desc()).first().ip == "192.0.2.9"


def test_forged_address_cannot_dodge_the_ip_limit(ctx):
    """On retenait la première valeur, que le client écrit lui-même : en en
    changeant à chaque essai, il échappait à la limite par adresse."""
    client = app.test_client()
    for n in range(3):
        _login(client, "dupontj", "x", ip=f"203.0.113.{n}, 192.0.2.50")
    adresses = {a.ip for a in LoginAttempt.query.all()}
    assert adresses == {"192.0.2.50"}, "une seule adresse réelle derrière les faux"


def test_old_attempts_are_purged(ctx):
    db.session.add(LoginAttempt(username="vieux", ip="1.1.1.1", success=False,
                                created_at=datetime.utcnow() - timedelta(days=31)))
    db.session.commit()
    _login(app.test_client(), "dupontj", "x")
    assert LoginAttempt.query.filter_by(username="vieux").count() == 0


# --- page de connexion : moins de blocages par faute de frappe -----------------
#
# Les mots de passe sont aléatoires (« Kx7m-Rp2v-Q9wT »), pénibles à taper sur
# un téléphone, et cinq échecs bloquent l'identifiant quinze minutes.

import html as _html


def _texte(reponse):
    return _html.unescape(reponse.data.decode())


def test_pasted_password_with_surrounding_spaces_is_accepted(ctx):
    """Un copier-coller depuis l'e-mail d'identifiants embarque souvent une
    espace en fin de ligne : l'échec comptait pour le blocage."""
    assert _login(app.test_client(), "dupontj", f"  {PASSWORD} \n").status_code == 302
    assert LoginAttempt.query.filter_by(success=False).count() == 0


def test_spaces_inside_are_not_forgiven(ctx):
    """Seules les espaces autour sont tolérées : le mot de passe lui-même
    doit rester exact."""
    assert _login(app.test_client(), "dupontj", PASSWORD.replace("-", " ")).status_code == 200


def test_a_chosen_password_with_spaces_still_works_as_typed(ctx):
    """Le mot de passe du superadministrateur initial a été choisi, pas
    généré : on essaie toujours la saisie exacte d'abord."""
    ctx.set_password("mon mot de passe ")
    db.session.commit()
    assert _login(app.test_client(), "dupontj", "mon mot de passe ").status_code == 302


def test_warning_before_the_lock(ctx):
    """Prévenir avant le blocage plutôt que le découvrir."""
    client = app.test_client()
    messages = [_texte(_login(client, "dupontj", "faux")) for _ in range(5)]
    assert "Attention" not in messages[0] and "Attention" not in messages[1]
    assert "encore 2 essais avant un blocage de 15 minutes" in messages[2]
    assert "encore 1 essai avant un blocage" in messages[3]
    assert "Connexion bloquée 15 minutes" in messages[4]


def test_password_field_is_ready_for_phones(ctx):
    html = app.test_client().get("/login").data.decode()
    champ = html.split('id="password"')[0].rsplit("<input", 1)[1] + html.split('id="password"')[1].split(">")[0]
    assert 'autocomplete="current-password"' in champ, "le téléphone propose d'enregistrer"
    assert 'autocapitalize="none"' in champ
    assert 'autocorrect="off"' in champ
    assert 'spellcheck="false"' in champ, "affiché en clair, le clavier ne doit rien corriger"


def test_show_password_button_is_accessible(ctx):
    html = app.test_client().get("/login").data.decode()
    bouton = html.split('id="passwordToggle"')[1].split(">")[0]
    assert 'aria-controls="password"' in bouton
    assert 'aria-pressed="false"' in bouton
    assert 'aria-label="Afficher le mot de passe"' in bouton
    assert 'type="button"' in html.split('id="passwordToggle"')[0].rsplit("<button", 1)[1], \
        "un bouton de type submit enverrait le formulaire"
