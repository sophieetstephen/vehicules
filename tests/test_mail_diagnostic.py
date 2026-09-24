"""Diagnostic de l'envoi des e-mails, depuis l'application.

Signalé : « quand je crée un utilisateur, un message dit que le mail n'est pas
parti ». L'erreur exacte n'existait que dans le journal du conteneur, et
l'administrateur est le plus souvent sur son téléphone, sans terminal. Cette
page donne la configuration, déclenche un envoi de test et traduit l'erreur.
"""

import html as html_module
import importlib
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, explain_mail_error, mail_settings_summary, missing_mail_settings, try_mail
from models import db, User

app_module = importlib.import_module("app")


@pytest.fixture
def ctx():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.drop_all()


@pytest.fixture
def messagerie(monkeypatch):
    """Une configuration d'envoi complète et plausible."""
    for cle, valeur in (("MAIL_SERVER", "smtp.gmail.com"), ("MAIL_PORT", 587),
                        ("MAIL_USE_TLS", True), ("MAIL_USERNAME", "centre@gmail.com"),
                        ("MAIL_PASSWORD", "abcd" * 4),
                        ("MAIL_DEFAULT_SENDER", "centre@gmail.com")):
        monkeypatch.setitem(app.config, cle, valeur)


def _user(role=User.ROLE_SUPERADMIN, email="chef@ex.fr"):
    u = User(name="Chef Alex", first_name="Alex", last_name="Chef", email=email,
             role=role, status="active", password_hash="x")
    db.session.add(u)
    db.session.flush()
    u.assign_username()
    db.session.commit()
    return u


def _texte(reponse):
    """Le HTML rendu, apostrophes remises en clair.

    Jinja échappe « l\'identifiant » en « l&#39;identifiant » : chercher la
    phrase telle qu\'elle est écrite dans le code échouerait, ou pire,
    tomberait sur un libellé statique du gabarit et passerait à tort.
    """
    return html_module.unescape(reponse.data.decode())


def _client_as(user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = user.id
        s["pwd_stamp"] = user.session_stamp(app.config["SECRET_KEY"])
    return c


# --- ce que la page montre ---------------------------------------------------

def test_page_shows_the_settings_without_the_key(ctx, messagerie):
    """La page se consulte depuis un téléphone, parfois devant quelqu'un."""
    html = _texte(_client_as(_user()).get("/admin/mail-test"))
    assert "smtp.gmail.com" in html
    assert "centre@gmail.com" in html
    assert "16 caractères" in html
    assert "abcdabcdabcdabcd" not in html, "la clé ne doit jamais s'afficher"


def test_incomplete_settings_are_named(ctx, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_SERVER", "smtp.gmail.com")
    monkeypatch.setitem(app.config, "MAIL_USERNAME", "")
    monkeypatch.setitem(app.config, "MAIL_PASSWORD", "")
    html = _client_as(_user()).get("/admin/mail-test").data.decode()
    assert "MAIL_USERNAME" in html
    assert "MAIL_PASSWORD" in html


def test_unusual_key_length_is_flagged(ctx, monkeypatch):
    """Une clé d'application Google fait seize caractères : une autre longueur
    trahit souvent un copier-coller incomplet."""
    for cle, valeur in (("MAIL_SERVER", "smtp.gmail.com"),
                        ("MAIL_USERNAME", "centre@gmail.com"),
                        ("MAIL_PASSWORD", "trop-court")):
        monkeypatch.setitem(app.config, cle, valeur)
    html = _texte(_client_as(_user()).get("/admin/mail-test"))
    assert "une clé Google en compte seize" in html


# --- l'envoi de test ---------------------------------------------------------

def test_successful_test_is_reported(ctx, messagerie, monkeypatch):
    envois = []
    monkeypatch.setattr(app_module, "send_mail_msmtp",
                        lambda sujet, corps, dest: envois.append(dest) or (True, "sent"))
    html = _texte(_client_as(_user()).post("/admin/mail-test"))
    assert "Message de test envoyé" in html
    assert envois == [["chef@ex.fr"]], "le test part vers sa propre adresse"


def test_failure_is_explained_in_plain_french(ctx, messagerie, monkeypatch):
    monkeypatch.setattr(app_module, "send_mail_msmtp",
                        lambda *a, **k: (False, "smtp error: (535, b'5.7.8 Username and Password not accepted')"))
    html = _texte(_client_as(_user()).post("/admin/mail-test"))
    assert "L'envoi a échoué" in html
    # Phrase propre à l'explication, absente des libellés du gabarit.
    assert "Google a refusé l'identifiant ou la clé d'application" in html
    # Le message brut reste consultable, replié.
    assert "5.7.8" in html


def test_exception_is_caught(ctx, messagerie, monkeypatch):
    """Une panne réseau lève au lieu de renvoyer un couple : la page ne doit
    pas répondre par une erreur 500."""
    def explose(*a, **k):
        raise OSError("timed out")

    monkeypatch.setattr(app_module, "send_mail_msmtp", explose)
    reponse = _client_as(_user()).post("/admin/mail-test")
    assert reponse.status_code == 200
    assert "Le serveur d'envoi n'a pas répondu" in _texte(reponse)


def test_nothing_is_sent_when_settings_are_missing(ctx, monkeypatch):
    """Inutile d'attendre un délai réseau pour apprendre qu'il manque la clé."""
    for cle in ("MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD"):
        monkeypatch.setitem(app.config, cle, "")
    appels = []
    monkeypatch.setattr(app_module, "send_mail_msmtp",
                        lambda *a, **k: appels.append(1) or (True, "sent"))
    html = _texte(_client_as(_user()).post("/admin/mail-test"))
    assert not appels, "aucun envoi ne doit être tenté"
    assert "Il manque" in html


def test_user_without_email_is_told_so(ctx, messagerie):
    reussi, _, explication = try_mail("")
    assert reussi is False
    assert "destinataire" in explication


# --- traductions -------------------------------------------------------------

@pytest.mark.parametrize("brut,attendu", [
    ("535 5.7.8 Username and Password not accepted", "clé d'application"),
    ("Connection refused", "port est probablement bloqué"),
    ("[Errno -2] Name or service not known", "nom du serveur d'envoi"),
    ("[SSL: WRONG_VERSION_NUMBER] wrong version number", "port et le mode de chiffrement"),
    ("553 Sender address rejected", "adresse d'expéditeur"),
])
def test_common_failures_are_translated(brut, attendu):
    explication = explain_mail_error(brut)
    assert explication and attendu in explication, brut


def test_unknown_error_is_not_invented():
    """Mieux vaut le message brut qu'une explication fausse."""
    assert explain_mail_error("erreur totalement inedite 12345") is None


# --- accès -------------------------------------------------------------------

@pytest.mark.parametrize("role", [User.ROLE_USER, User.ROLE_ADMIN])
def test_page_is_reserved_to_the_superadmin(ctx, role):
    """Elle révèle le compte d'envoi et déclenche des messages."""
    reponse = _client_as(_user(role=role, email=f"{role}@ex.fr")).get("/admin/mail-test")
    assert reponse.status_code in (302, 403), reponse.status_code


def test_tile_leads_to_the_page(ctx, messagerie):
    html = _client_as(_user()).get("/").data.decode()
    assert "/admin/mail-test" in html
    assert "Envoi des e-mails" in html


# --- expéditeur --------------------------------------------------------------

def test_sender_follows_the_configuration():
    """L'adresse était écrite en dur dans notify.py alors que l'identifiant de
    connexion vient du .env : changer de compte aurait fait refuser les envois.
    """
    source = open("notify.py", encoding="utf-8").read()
    signature = source.split("def send_mail_msmtp")[1].split("\n")[0]
    assert 'sender: str = ""' in signature, "plus d'adresse en dur dans la signature"
    assert "Config.MAIL_DEFAULT_SENDER" in source
    assert "Config.MAIL_USERNAME" in source


# --- lisible sur un téléphone ------------------------------------------------

def test_alert_holds_a_single_block_after_its_icon():
    """``.alert`` est en ``display: flex`` : chaque enfant direct devient une
    colonne. Le message, l'explication et le détail technique se retrouvaient
    côte à côte, en bandes de quelques mots de large."""
    gabarit = pathlib.Path("templates/mail_test.html").read_text(encoding="utf-8")
    for alerte in gabarit.split('<div class="alert')[1:]:
        corps = alerte.split("</div>")[0]
        apres_icone = corps.split("</i>")[1] if "</i>" in corps else corps
        assert apres_icone.strip().startswith("<div>"), apres_icone.strip()[:60]


def test_technical_message_wraps():
    """Une erreur SMTP n'a pas de mots courts : sans coupure elle sortait de
    l'écran, mesuré à 140 pixels de débordement."""
    css = pathlib.Path("static/custom.css").read_text(encoding="utf-8")
    bloc = css.split(".alert code,")[1].split("}")[0]
    assert "overflow-wrap: anywhere" in bloc


# --- alerte préventive -------------------------------------------------------
#
# La clé d'application avait été révoquée sans prévenir : plus personne ne
# recevait ses identifiants, et la panne n'a été découverte qu'en créant un
# compte. L'état de l'envoi est désormais suivi, et signalé sur l'accueil.

from datetime import datetime, timedelta


def _etat(ok, *, il_y_a_jours=0, detail=""):
    """Poser un état de départ, daté."""
    quand = app_module.local_now() - timedelta(days=il_y_a_jours)
    return app_module.write_mail_health(ok, detail, checked_at=quand)


def test_a_real_send_records_the_state(ctx, messagerie, monkeypatch):
    """L'information la plus fraîche est le résultat d'un envoi réel."""
    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (True, "sent"))
    with app.test_request_context("/"):
        app_module.notify("Sujet", "Corps", "jean@ex.fr")
    assert app_module.read_mail_health()["ok"] is True

    monkeypatch.setattr(app_module, "send_mail_msmtp", lambda *a, **k: (False, "535 refused"))
    with app.test_request_context("/"):
        app_module.notify("Sujet", "Corps", "jean@ex.fr")
    etat = app_module.read_mail_health()
    assert etat["ok"] is False
    assert etat["failing_since"] is not None


def test_failure_start_date_is_kept(ctx, messagerie):
    """« Depuis le … » doit désigner le début de la panne, pas le dernier
    contrôle."""
    _etat(False, il_y_a_jours=3, detail="535 refused")
    debut = app_module.read_mail_health()["failing_since"]
    app_module.write_mail_health(False, "535 refused")
    assert app_module.read_mail_health()["failing_since"] == debut


def test_recovery_clears_the_alert(ctx, messagerie):
    _etat(False, il_y_a_jours=3, detail="535 refused")
    app_module.write_mail_health(True, "sent")
    etat = app_module.read_mail_health()
    assert etat["ok"] is True and etat["failing_since"] is None
    assert app_module.mail_alert() is None


def test_check_runs_at_most_once_a_week(ctx, messagerie, monkeypatch):
    """Une authentification à chaque ouverture de l'accueil serait inutile."""
    appels = []
    monkeypatch.setattr(app_module, "check_mail_login",
                        lambda *a, **k: appels.append(1) or (True, "login ok"))

    _etat(True, il_y_a_jours=2)
    app_module.refresh_mail_health_if_due()
    assert appels == [], "contrôle récent : rien à refaire"

    _etat(True, il_y_a_jours=8)
    app_module.refresh_mail_health_if_due()
    assert len(appels) == 1, "au-delà d'une semaine, on revérifie"


def test_check_does_not_send_anything(ctx, messagerie, monkeypatch):
    """On s'authentifie et on referme : personne ne reçoit de message inutile."""
    envois = []
    monkeypatch.setattr(app_module, "send_mail_msmtp",
                        lambda *a, **k: envois.append(1) or (True, "sent"))
    monkeypatch.setattr(app_module, "check_mail_login", lambda *a, **k: (True, "login ok"))
    app_module.refresh_mail_health_if_due(force=True)
    assert envois == []


def test_banner_appears_for_admins(ctx, messagerie, monkeypatch):
    monkeypatch.setattr(app_module, "check_mail_login", lambda *a, **k: (False, "535 refused"))
    for role in (User.ROLE_ADMIN, User.ROLE_SUPERADMIN):
        db.session.query(User).delete()
        db.session.commit()
        html = _texte(_client_as(_user(role=role, email=f"{role}@ex.fr")).get("/"))
        assert "Les e-mails ne partent plus" in html, role
        assert "Google a refusé" in html, role


def test_banner_is_not_shown_to_a_regular_user(ctx, messagerie, monkeypatch):
    """Ce n'est pas son affaire, et il ne peut rien y faire."""
    monkeypatch.setattr(app_module, "check_mail_login", lambda *a, **k: (False, "535 refused"))
    app_module.write_mail_health(False, "535 refused")
    html = _texte(_client_as(_user(role=User.ROLE_USER, email="jean@ex.fr")).get("/"))
    assert "Les e-mails ne partent plus" not in html


def test_no_banner_when_everything_works(ctx, messagerie, monkeypatch):
    monkeypatch.setattr(app_module, "check_mail_login", lambda *a, **k: (True, "login ok"))
    html = _texte(_client_as(_user()).get("/"))
    assert "Les e-mails ne partent plus" not in html


def test_banner_names_the_missing_settings(ctx, monkeypatch):
    for cle in ("MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD"):
        monkeypatch.setitem(app.config, cle, "")
    html = _texte(_client_as(_user()).get("/"))
    assert "Les e-mails ne partent plus" in html
    assert "MAIL_PASSWORD" in html


def test_banner_says_since_when(ctx, messagerie, monkeypatch):
    monkeypatch.setattr(app_module, "check_mail_login", lambda *a, **k: (False, "535 refused"))
    _etat(False, il_y_a_jours=4, detail="535 refused")
    html = _texte(_client_as(_user()).get("/"))
    attendu = (app_module.local_now() - timedelta(days=4)).strftime("%d/%m/%Y")
    assert f"Depuis le {attendu}" in html


def test_unreadable_state_file_is_survivable(ctx, messagerie, tmp_path):
    """Un fichier tronqué ne doit pas empêcher l'accueil de s'afficher."""
    chemin = tmp_path / "casse.json"
    chemin.write_text("{ ceci n'est pas du json", encoding="utf-8")
    app.config["MAIL_HEALTH_PATH"] = str(chemin)
    assert app_module.read_mail_health() is None
    assert app_module.mail_alert() is None


def test_state_file_stays_out_of_the_instance_folder_in_tests():
    """Le piège déjà rencontré avec la base : écrire dans le dossier réel."""
    assert app.config.get("MAIL_HEALTH_PATH"), "conftest doit isoler ce fichier"
    assert "vehicules/instance" not in app.config["MAIL_HEALTH_PATH"]


# --- délai d'envoi -------------------------------------------------------------

def test_real_send_has_a_timeout(monkeypatch):
    """Sans délai, un serveur muet bloquait indéfiniment la page qui avait
    déclenché l'envoi."""
    import notify

    vus = {}

    class FauxSMTP:
        def __init__(self, serveur, port, timeout=None, **_):
            vus["timeout"] = timeout
            raise OSError("arret du test")

    monkeypatch.setattr(notify.smtplib, "SMTP", FauxSMTP)
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FauxSMTP)
    ok, _ = notify.send_mail_msmtp("Sujet", "Corps", ["a@ex.fr"])
    assert ok is False
    assert vus["timeout"] and vus["timeout"] <= 30


# --- certificat du serveur d'envoi ---------------------------------------------
#
# Sans contexte, la connexion était chiffrée mais le certificat jamais vérifié :
# un serveur qui se faisait passer pour Gmail recevait la clé d'application.
# On monte ce faux serveur, avec un certificat qu'aucune autorité n'a signé.

@pytest.fixture
def faux_gmail(tmp_path, monkeypatch):
    import shutil
    import socket
    import ssl
    import subprocess
    import threading

    import notify

    if shutil.which("openssl") is None:
        pytest.skip("openssl est nécessaire pour fabriquer le certificat")
    cle, cert = tmp_path / "cle.pem", tmp_path / "cert.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(cle), "-out", str(cert), "-days", "1",
                    "-subj", "/CN=smtp.gmail.com"], check=True, capture_output=True)

    contexte = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexte.load_cert_chain(cert, cle)
    ecoute = socket.socket()
    ecoute.bind(("127.0.0.1", 0))
    ecoute.listen(1)
    recu = []

    def servir():
        conn, _ = ecoute.accept()
        try:
            with contexte.wrap_socket(conn, server_side=True) as tls:
                tls.sendall(b"220 faux gmail\r\n")
                recu.append(tls.recv(1024))
        except (ssl.SSLError, OSError):
            pass  # le client a refusé la poignée de main : c'est le but

    fil = threading.Thread(target=servir, daemon=True)
    fil.start()
    monkeypatch.setattr(notify.Config, "MAIL_SERVER", "127.0.0.1")
    monkeypatch.setattr(notify.Config, "MAIL_PORT", ecoute.getsockname()[1])
    monkeypatch.setattr(notify.Config, "MAIL_USE_TLS", False)
    monkeypatch.setattr(notify.Config, "MAIL_USERNAME", "compte@gmail.com")
    monkeypatch.setattr(notify.Config, "MAIL_PASSWORD", "cle-application")
    yield recu
    fil.join(timeout=5)
    ecoute.close()


def test_impostor_server_is_refused_before_login(faux_gmail):
    import notify

    ok, detail = notify.check_mail_login(timeout=5)
    assert ok is False
    assert "certificate verify failed" in detail.lower()
    assert faux_gmail == [], "le client a parlé à un serveur non vérifié"


def test_impostor_server_never_receives_a_message(faux_gmail):
    import notify

    ok, detail = notify.send_mail_msmtp("Sujet", "Corps", ["a@ex.fr"])
    assert ok is False
    assert faux_gmail == []


def test_certificate_error_is_explained():
    """Le message contient « ssl » : sans règle dédiée, il était pris pour un
    mauvais réglage de port."""
    explication = app_module.explain_mail_error(
        "smtp error: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    assert "certificat" in explication
    assert "port" not in explication
