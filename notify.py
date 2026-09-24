from email.message import EmailMessage
import smtplib
import ssl
from config import Config

# Délai d'envoi. Sans lui, un serveur muet bloquait indéfiniment la page qui
# avait déclenché l'envoi — validation d'une réservation, création d'un compte.
SEND_TIMEOUT = 15


def _smtp_connect(server, port, timeout):
    """Connexion chiffrée au serveur d'envoi, certificat vérifié.

    Sans contexte, ``starttls()`` et ``SMTP_SSL`` chiffrent sans vérifier le
    certificat : un intermédiaire pouvait se faire passer pour Gmail et
    recueillir la clé d'application. Le contexte par défaut vérifie le
    certificat et le nom du serveur.
    """

    contexte = ssl.create_default_context()
    if Config.MAIL_USE_TLS:
        smtp = smtplib.SMTP(server, port, timeout=timeout)
        try:
            smtp.starttls(context=contexte)
        except Exception:
            smtp.close()
            raise
        return smtp
    return smtplib.SMTP_SSL(server, port, timeout=timeout, context=contexte)


def send_mail_msmtp(subject: str, body: str, to_addrs, sender: str = "", profile: str = "gmail"):
    """Send an email using Gmail's SMTP service.

    The signature mirrors the previous msmtp-based helper to avoid breaking
    existing calls or tests. The ``profile`` argument is kept for backward
    compatibility but ignored.
    """

    if isinstance(to_addrs, str):
        to_list = [to_addrs]
    else:
        to_list = list(to_addrs)

    # L'adresse d'expediteur etait ecrite en dur alors que l'identifiant de
    # connexion vient du .env : changer de compte Gmail sans toucher a cette
    # ligne aurait fait refuser tous les envois.
    expediteur = (sender or Config.MAIL_DEFAULT_SENDER or Config.MAIL_USERNAME
                  or "gestionvehiculestomer@gmail.com")

    msg = EmailMessage()
    msg["From"] = expediteur
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content(body)

    server = Config.MAIL_SERVER or "smtp.gmail.com"
    port = Config.MAIL_PORT or (465 if not Config.MAIL_USE_TLS else 587)

    try:
        with _smtp_connect(server, port, SEND_TIMEOUT) as smtp:
            smtp.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            smtp.send_message(msg)
        return True, "sent"
    except Exception as e:
        return False, f"smtp error: {e}"


def check_mail_login(timeout: int = 6):
    """Vérifier que le compte d'envoi est toujours accepté, sans rien envoyer.

    On se connecte et on s'authentifie, puis on referme. C'est exactement ce
    qui échoue quand Google révoque une clé d'application, et personne ne
    reçoit de message inutile.

    Le délai est court : ce contrôle a lieu pendant l'affichage de l'accueil
    d'un administrateur, qui ne doit pas rester bloqué sur un serveur muet.

    Retourne ``(ok, détail)``.
    """

    server = Config.MAIL_SERVER or "smtp.gmail.com"
    port = Config.MAIL_PORT or (465 if not Config.MAIL_USE_TLS else 587)

    try:
        with _smtp_connect(server, port, timeout) as smtp:
            smtp.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
        return True, "login ok"
    except Exception as e:
        return False, f"smtp error: {e}"
